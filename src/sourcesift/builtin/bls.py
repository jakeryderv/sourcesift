"""Official US labor and price statistics from the Bureau of Labor Statistics API."""

from typing import Literal
from urllib.parse import urlencode

from pydantic import Field

from sourcesift.builtin.common import json_object, number, one_line, with_unit
from sourcesift.contract import Contract
from sourcesift.data import Cell, Column, Table
from sourcesift.extend import FetchContext, Record, SourceResult, source
from sourcesift.retrieval.urls import RetrievalError

_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
# series -> (BLS series ID, title, column name, unit, add a 12-month change column)
_SERIES = {
    "unemployment-rate": (
        "LNS14000000",
        "US unemployment rate, seasonally adjusted",
        "Unemployment rate",
        "%",
        False,
    ),
    "labor-force-participation": (
        "LNS11300000",
        "US labor force participation rate, seasonally adjusted",
        "Labor force participation rate",
        "%",
        False,
    ),
    "nonfarm-payrolls": (
        "CES0000000001",
        "US total nonfarm employment, seasonally adjusted",
        "Nonfarm employment",
        "thousand jobs",
        False,
    ),
    "average-hourly-earnings": (
        "CES0500000003",
        "US average hourly earnings, private employees, seasonally adjusted",
        "Average hourly earnings",
        "USD",
        True,
    ),
    "consumer-prices": (
        "CUUR0000SA0",
        "US Consumer Price Index for All Urban Consumers, all items",
        "CPI-U (1982-84=100)",
        "",
        True,
    ),
    "core-consumer-prices": (
        "CUUR0000SA0L1E",
        "US Consumer Price Index, all items less food and energy",
        "Core CPI-U (1982-84=100)",
        "",
        True,
    ),
}
_CHANGE = "12-month change"


class BlsParams(Contract):
    """Which monthly series to read, and how far back."""

    series: Literal[
        "unemployment-rate",
        "labor-force-participation",
        "nonfarm-payrolls",
        "average-hourly-earnings",
        "consumer-prices",
        "core-consumer-prices",
    ] = Field(
        description="'unemployment-rate' and 'labor-force-participation' (percent); "
        "'nonfarm-payrolls' (thousands of jobs); 'average-hourly-earnings' (dollars); "
        "'consumer-prices' and 'core-consumer-prices' (the CPI index, with its "
        "12-month percent change, which is the inflation rate)."
    )
    years: int = Field(
        default=5, ge=1, le=9, description="How many years of monthly history."
    )


@source(
    id="bls",
    name="US Bureau of Labor Statistics",
    website="https://www.bls.gov/",
    aliases=("BLS", "Bureau of Labor Statistics"),
    description="Official monthly US labor and price statistics with history: "
    "unemployment rate, labor force participation, nonfarm employment, average "
    "hourly earnings, and consumer prices (CPI) with the 12-month inflation rate.",
    topics=("economics", "labor", "government-data"),
    geography="United States",
    params=BlsParams,
    api_hosts=("api.bls.gov",),
)
async def bls(params: BlsParams, context: FetchContext) -> SourceResult:
    """One monthly series as evidence text plus a table of the same values."""
    series_id, title, column, unit, change = _SERIES[params.series]
    end = context.now.year
    # A 12-month change needs the year before the first one shown.
    start = end - params.years - (1 if change else 0)
    page = await context.get(
        f"{_API}{series_id}?" + urlencode({"startyear": start, "endyear": end})
    )
    data = json_object(page)
    if data.get("status") != "REQUEST_SUCCEEDED":
        messages = data.get("message")
        detail = one_line(
            messages[0] if isinstance(messages, list) and messages else ""
        )
        raise RetrievalError(
            "The statistics service refused the request"
            + (f": {detail}" if detail else ".")
        )
    results = data.get("Results")
    listed = results.get("series") if isinstance(results, dict) else None
    first = listed[0] if isinstance(listed, list) and listed else None
    observations = first.get("data") if isinstance(first, dict) else None
    months: dict[str, tuple[float, bool]] = {}
    for item in observations if isinstance(observations, list) else []:
        if not isinstance(item, dict):
            continue
        period = one_line(item.get("period"), 4)
        year = one_line(item.get("year"), 4)
        value = number(item.get("value"))
        # M13 is an annual average; only calendar months are observations.
        if (
            len(period) == 3
            and period[0] == "M"
            and period[1:].isdigit()
            and 1 <= int(period[1:]) <= 12
            and year.isdigit()
            and value is not None
        ):
            notes = item.get("footnotes")
            preliminary = any(
                isinstance(note, dict) and note.get("code") == "P"
                for note in (notes if isinstance(notes, list) else [])
            )
            months[f"{year}-{period[1:]}-01"] = (value, preliminary)
    if not months:
        raise RetrievalError("The series returned no monthly values.")
    rows: list[tuple[Cell, ...]] = []
    for day in sorted(months):
        value = months[day][0]
        if change:
            before = months.get(f"{int(day[:4]) - 1}{day[4:]}")
            if int(day[:4]) <= start:
                continue
            rows.append(
                (
                    day,
                    value,
                    round((value / before[0] - 1) * 100, 2) if before else None,
                )
            )
        else:
            rows.append((day, value))
    if not rows:
        raise RetrievalError("The series returned no monthly values.")

    def said(row: tuple[Cell, ...]) -> str:
        text = f"{str(row[0])[:7]}: {with_unit(float(row[1] or 0), unit)}"
        if change and row[2] is not None:
            text += f" ({row[2]:+.2f}% from a year earlier)"
        return text + (" (preliminary)" if months[str(row[0])][1] else "")

    latest = rows[-1]
    text = (
        f"{title}, from the US Bureau of Labor Statistics (series {series_id}). "
        f"Monthly values; the month is the reference period, not a publication date. "
        f"Latest: {said(latest)}.\n"
        + "\n".join(said(row) for row in reversed(rows[-13:]))
        + f"\nHistory retrieved: {len(rows)} months from {str(rows[0][0])[:7]} "
        f"({with_unit(float(rows[0][1] or 0), unit)}) to {str(latest[0])[:7]}."
    )
    if change:
        text += (
            f" The {_CHANGE} is computed by SourceSift from the index values "
            "retrieved; BLS publishes the same measure."
        )
    table = Table(
        name=f"{title}, {str(rows[0][0])[:7]} to {str(latest[0])[:7]}"[:120],
        columns=(
            Column(name="Month", kind="time"),
            Column(name=column, unit=unit),
            *((Column(name=_CHANGE, unit="%"),) if change else ()),
        ),
        rows=tuple(rows),
    )
    record = Record(f"{title} (as of {str(latest[0])[:7]})", page.url, text, page)
    return SourceResult([record], (table,))
