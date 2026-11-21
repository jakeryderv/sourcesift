"""Official figures from the US Treasury Fiscal Data API."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlencode

from pydantic import Field

from sourcesift.builtin.common import json_object, number, one_line
from sourcesift.contract import Contract
from sourcesift.data import Column, Point, Series, Stat, Stats, Table, TimeSeries
from sourcesift.extend import FetchContext, Record, SourceResult, source
from sourcesift.retrieval.http import Page
from sourcesift.retrieval.urls import RetrievalError

_API = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
_SKIP = ("src_line_nbr", "record_fiscal_", "record_calendar_")
_DEBT = {
    "tot_pub_debt_out_amt": "Total public debt outstanding",
    "debt_held_public_amt": "Debt held by the public",
    "intragov_hold_amt": "Intragovernmental holdings",
}
# dataset -> (title, API path, latest rows to request, (name column, value column, unit))
_TABLES = {
    "interest-rates": (
        "Average Interest Rates on US Treasury Securities",
        "v2/accounting/od/avg_interest_rates",
        40,
        ("security_desc", "avg_interest_rate_amt", "%"),
    ),
    # About 170 currencies.
    "exchange-rates": (
        "Treasury Reporting Rates of Exchange",
        "v1/accounting/od/rates_of_exchange",
        200,
        ("country_currency_desc", "exchange_rate", "per USD"),
    ),
}


class TreasuryParams(Contract):
    """Which Treasury dataset to read."""

    dataset: Literal["debt", "interest-rates", "exchange-rates"] = Field(
        description="'debt': total public debt outstanding by day. 'interest-rates': "
        "average interest rates on Treasury securities, latest month. "
        "'exchange-rates': Treasury reporting rates of exchange, latest quarter."
    )
    days: int = Field(
        default=30,
        ge=7,
        le=3650,
        description="For 'debt' only: how many days of history to return.",
    )


def _rows(page: Page) -> tuple[list[dict[str, object]], dict[str, object]]:
    data = json_object(page)
    listed = data.get("data")
    rows = [
        row
        for row in (listed if isinstance(listed, list) else [])
        if isinstance(row, dict)
    ]
    if not rows:
        raise RetrievalError("The dataset returned no rows.")
    meta = data.get("meta")
    labels = meta.get("labels") if isinstance(meta, dict) else None
    return rows, labels if isinstance(labels, dict) else {}


def _day(row: dict[str, object]) -> datetime | None:
    try:
        return datetime.fromisoformat(one_line(row.get("record_date"), 10)).replace(
            tzinfo=UTC
        )
    except ValueError:
        return None


async def _debt(params: TreasuryParams, context: FetchContext) -> SourceResult:
    since = (context.now - timedelta(days=params.days)).date().isoformat()
    page = await context.get(
        _API
        + "v2/accounting/od/debt_to_penny?"
        + urlencode(
            {
                "fields": "record_date," + ",".join(_DEBT),
                "filter": f"record_date:gte:{since}",
                "sort": "-record_date",
                "page[size]": 3000,
            }
        )
    )
    rows, _ = _rows(page)
    latest = one_line(rows[0].get("record_date"), 20) or "unknown date"
    series = []
    stats = []
    for field, label in _DEBT.items():
        points = [
            Point(at=day, value=value)
            for row in reversed(rows)
            if (day := _day(row)) is not None
            and (value := number(row.get(field))) is not None
        ]
        if not points:
            continue
        series.append(Series(name=label, points=tuple(points)))
        change = points[-1].value - points[-2].value if len(points) > 1 else None
        stats.append(
            Stat(label=label, value=points[-1].value, unit="USD", change=change)
        )
    if not series:
        raise RetrievalError("The dataset returned no usable values.")
    total = series[0].points
    lines = [
        f"{one_line(row.get('record_date'), 20)}: "
        + "; ".join(
            f"{label}: {one_line(row.get(field), 40)}" for field, label in _DEBT.items()
        )
        for row in rows[:5]
    ]
    text = (
        "Debt to the Penny, from the US Treasury Fiscal Data API. Amounts are as "
        f"published, in US dollars. Latest record date: {latest}.\n"
        + "\n".join(lines)
        + f"\nHistory retrieved: {len(total)} daily records from "
        f"{total[0].at.date().isoformat()} ({total[0].value:.2f}) to "
        f"{total[-1].at.date().isoformat()} ({total[-1].value:.2f}); "
        f"{series[0].name.lower()} changed by {total[-1].value - total[0].value:.2f} "
        "over that period."
    )
    # A record date is a reporting period, not a publication time, so the record
    # carries no publication date and is not filtered by the request's window.
    return SourceResult(
        [Record(f"Debt to the Penny (as of {latest})", page.url, text, page)],
        (
            TimeSeries(name="US public debt", unit="USD", series=tuple(series)),
            Stats(name=f"US public debt as of {latest}", items=tuple(stats)),
        ),
    )


@source(
    id="us-treasury",
    name="US Treasury Fiscal Data",
    website="https://fiscaldata.treasury.gov/",
    aliases=("Treasury", "Fiscal Data"),
    description="Official US Treasury figures: public debt by day with history, and "
    "the latest average interest rates on Treasury securities and reporting rates "
    "of exchange. Not stock prices or market quotes.",
    topics=("economics", "finance", "government-data"),
    geography="United States",
    params=TreasuryParams,
    returns=(TimeSeries, Stats, Table),
)
async def us_treasury(params: TreasuryParams, context: FetchContext) -> SourceResult:
    """One Treasury dataset as evidence text plus a series, figures, or a table."""
    if params.dataset == "debt":
        return await _debt(params, context)
    title, path, size, (name, value, unit) = _TABLES[params.dataset]
    page = await context.get(
        _API + f"{path}?" + urlencode({"sort": "-record_date", "page[size]": size})
    )
    rows, labels = _rows(page)
    latest = one_line(rows[0].get("record_date"), 20)
    # These datasets publish many rows per period; keep the latest period only.
    rows = [row for row in rows if one_line(row.get("record_date"), 20) == latest]
    if params.dataset == "exchange-rates":
        # A fixed name-and-value pair per row needs no repeated column labels.
        lines = [
            f"{one_line(row.get(name), 120)}: {one_line(row.get(value), 120)}"
            for row in rows
        ]
    else:
        lines = [
            "; ".join(
                f"{one_line(labels.get(key, key), 80)}: {one_line(item, 120)}"
                for key, item in row.items()
                if not key.startswith(_SKIP) and item not in (None, "null")
            )
            for row in rows
        ]
    text = (
        f"{title}, from the US Treasury Fiscal Data API. Latest record date: "
        f"{latest or 'unknown'}. Amounts are as published, in US dollars or percent.\n"
        + "\n".join(lines)
    )
    label = latest or "unknown date"
    table = Table(
        name=f"{title} (as of {label})"[:120],
        columns=(
            Column(name=one_line(labels.get(name, "Name"), 80) or "Name"),
            Column(name=one_line(labels.get(value, "Value"), 80) or "Value", unit=unit),
        ),
        rows=tuple(
            (one_line(row.get(name), 120), number(row.get(value))) for row in rows
        ),
    )
    return SourceResult(
        [Record(f"{title} (as of {label})", page.url, text, page)], (table,)
    )
