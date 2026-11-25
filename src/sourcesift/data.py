"""Tables that sources return, and the figures drawn from them.

A source returns one or more ``Table`` values. A ``Figure`` is a chart of one
table: the columns and chart kind the model chose, with the rows the source
returned. The picture is drawn from that recipe by ``sourcesift.figures``, so a
figure's values never pass through the model.
"""

from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from sourcesift.contract import Contract

Cell = int | float | str | None
ColumnKind = Literal["text", "number", "time"]


class Column(Contract):
    """A table column; ``unit`` applies to every value in it.

    ``kind`` is worked out from the values unless given. Declare ``"time"`` for
    ISO 8601 dates or date-times, written in the zone they should be read in.
    """

    name: str = Field(min_length=1, max_length=80)
    unit: str = Field(default="", max_length=24)
    kind: ColumnKind | None = None


class Table(Contract):
    """Rows of values under uniquely named columns."""

    name: str = Field(min_length=1, max_length=120)
    columns: tuple[Column, ...] = Field(min_length=1, max_length=12)
    rows: tuple[tuple[Cell, ...], ...] = Field(max_length=5000)

    @model_validator(mode="after")
    def rows_match_columns(self) -> "Table":
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("every row needs one value per column")
        if len({column.name for column in self.columns}) != len(self.columns):
            raise ValueError("column names must be unique")
        return self

    def index(self, name: str) -> int:
        """Position of the named column; ``ValueError`` names the ones that exist."""
        for position, column in enumerate(self.columns):
            if column.name == name:
                return position
        known = ", ".join(column.name for column in self.columns)
        raise ValueError(f"There is no column {name!r}. Columns: {known}.")

    def kind(self, name: str) -> ColumnKind:
        """The column's declared kind, or number when every value present is one."""
        position = self.index(name)
        declared = self.columns[position].kind
        if declared is not None:
            return declared
        cells = [row[position] for row in self.rows if row[position] is not None]
        numeric = cells and all(
            isinstance(cell, int | float) and not isinstance(cell, bool)
            for cell in cells
        )
        return "number" if numeric else "text"

    def values(self, name: str) -> list[Cell]:
        position = self.index(name)
        return [row[position] for row in self.rows]

    def describe(self) -> dict[str, JsonValue]:
        """What the model needs in order to choose a chart and its columns."""
        return {
            "table": self.name,
            "rows": len(self.rows),
            "columns": [
                {"name": c.name, "kind": self.kind(c.name)}
                | ({"unit": c.unit} if c.unit else {})
                for c in self.columns
            ],
        }


PERIODS = ("day", "week", "month", "quarter", "year")
COMBINES = ("last", "first", "mean", "sum", "min", "max")


def _moment(cell: Cell, name: str) -> datetime:
    try:
        # Times are written in the zone they should be read in; drop the offset.
        return datetime.fromisoformat(str(cell)).replace(tzinfo=None)
    except ValueError:
        raise ValueError(
            f"Column {name!r} has a value that is not a date or time."
        ) from None


def _period_start(moment: datetime, period: str) -> date:
    day = moment.date()
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    if period == "quarter":
        return day.replace(month=3 * ((day.month - 1) // 3) + 1, day=1)
    if period == "year":
        return day.replace(month=1, day=1)
    return day


def _combined(values: list[float], combine: str) -> float | None:
    if not values:
        return None
    if combine == "mean":
        return sum(values) / len(values)
    return {"sum": sum, "min": min, "max": max}[combine](values)


def shape(
    table: Table,
    *,
    columns: tuple[str, ...] = (),
    period: str = "",
    combine: str = "last",
    since: str = "",
    top: int = 0,
) -> Table:
    """A smaller table made from ``table``; the values still come from its rows.

    ``columns`` keeps those columns, in that order (all of them when empty).
    ``since`` keeps rows on or after an ISO date. ``period`` (day, week, month,
    quarter, or year) leaves one row per period, combining each number column
    with ``combine``: the last or first value, or the mean, sum, min, or max.
    Text columns split each period into one row per distinct value. ``top``
    keeps that many rows with the largest values in the first number column.
    Raises ``ValueError``, worded for the model, when the table does not fit.
    """
    period, combine, since = (
        period.strip().lower(),
        combine.strip().lower(),
        since.strip(),
    )
    if period and period not in PERIODS:
        raise ValueError(f"period must be one of: {', '.join(PERIODS)}.")
    if combine not in COMBINES:
        raise ValueError(f"combine must be one of: {', '.join(COMBINES)}.")
    if top < 0:
        raise ValueError("top cannot be negative.")
    names = list(dict.fromkeys(columns)) or [column.name for column in table.columns]
    places = [table.index(name) for name in names]
    kinds = [table.kind(name) for name in names]
    kept = tuple(
        table.columns[place].model_copy(update={"kind": kind})
        for place, kind in zip(places, kinds, strict=True)
    )
    rows = [tuple(row[place] for place in places) for row in table.rows]
    numbers = [i for i, kind in enumerate(kinds) if kind == "number"]
    label = []
    if since or period:
        clock = next((i for i, kind in enumerate(kinds) if kind == "time"), None)
        if clock is None:
            raise ValueError("period and since need a time column among the columns.")
        timed = sorted(
            (
                (_moment(row[clock], names[clock]), row)
                for row in rows
                if row[clock] is not None
            ),
            key=lambda pair: pair[0],
        )
        if since:
            try:
                start = datetime.fromisoformat(since).replace(tzinfo=None)
            except ValueError:
                raise ValueError(
                    "since must be an ISO date such as 2026-01-31."
                ) from None
            timed = [pair for pair in timed if pair[0] >= start]
            label.append(f"since {since}")
        rows = [row for _, row in timed]
        if period:
            texts = [i for i, kind in enumerate(kinds) if kind == "text"]
            groups: dict[tuple, list[tuple]] = {}
            for moment, row in timed:
                key = (_period_start(moment, period), *(row[i] for i in texts))
                groups.setdefault(key, []).append(row)
            rows = []
            for key, members in groups.items():
                if combine in ("first", "last"):
                    # One recorded row stands for the period, with its own date.
                    order = members if combine == "first" else members[::-1]
                    rows.append(
                        next(
                            (
                                m
                                for m in order
                                if any(isinstance(m[i], int | float) for i in numbers)
                            ),
                            order[0],
                        )
                    )
                    continue
                row = list(members[-1])
                row[clock] = key[0].isoformat()
                for i in numbers:
                    present = [
                        float(m[i]) for m in members if isinstance(m[i], int | float)
                    ]
                    row[i] = _combined(present, combine)
                rows.append(tuple(row))
            label.append(f"{combine} per {period}")
    if top:
        if not numbers:
            raise ValueError("top needs a number column among the columns.")
        first = numbers[0]
        ranked = [row for row in rows if isinstance(row[first], int | float)]
        rows = sorted(ranked, key=lambda row: row[first], reverse=True)[:top]
        label.append(f"top {top}")
    if not rows:
        raise ValueError("No rows are left after that selection.")
    if not label and len(names) == len(table.columns):
        return table
    name = f"{table.name} ({', '.join(label)})" if label else table.name
    return Table(name=name[:120], columns=kept, rows=tuple(rows))


FigureKind = Literal["line", "area", "bar", "stacked_bar", "scatter", "donut"]


class Figure(Contract):
    """A chart of one table: what to plot, and the rows it is plotted from.

    ``id`` (F1, F2, ...) is stable within a conversation. Markdown places a figure
    with an image whose target is that ID, such as ``![Daily highs](F1)``. The
    table is a snapshot of the data when it was retrieved.
    """

    id: str = Field(pattern=r"^F[1-9]\d*$")
    title: str = Field(min_length=1, max_length=120)
    kind: FigureKind
    x: str
    y: tuple[str, ...] = Field(min_length=1, max_length=8)
    series: str = ""
    log_scale: bool = False
    source_id: str
    evidence_ids: tuple[str, ...]
    table: Table
