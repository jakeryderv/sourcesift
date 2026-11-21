"""Typed data shared by sources and widgets, and what a page can draw.

A source returns *shapes* (``TimeSeries``, ``Table``, ``Stats``). A widget accepts
one shape and returns a *view* (``Chart``, ``TableView``, ``StatView``), one of the
few things an interface knows how to draw. Sources and widgets never refer to each
other, so any widget can show any source's data of the shape it accepts.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from sourcesift.contract import Contract

Cell = int | float | str | None


class Point(Contract):
    """One value at a time; daily values use midnight UTC."""

    at: datetime
    value: float = Field(allow_inf_nan=False)


class Series(Contract):
    """One named line of values in time order."""

    name: str = Field(min_length=1, max_length=120)
    points: tuple[Point, ...] = Field(max_length=5000)


class TimeSeries(Contract):
    """Shape: one or more series over time that share a unit."""

    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(default="", max_length=24)
    series: tuple[Series, ...] = Field(min_length=1, max_length=12)


class Column(Contract):
    """A table column; ``unit`` applies to every value in it."""

    name: str = Field(min_length=1, max_length=80)
    unit: str = Field(default="", max_length=24)


class Table(Contract):
    """Shape: rows of values under named columns."""

    name: str = Field(min_length=1, max_length=120)
    columns: tuple[Column, ...] = Field(min_length=1, max_length=12)
    rows: tuple[tuple[Cell, ...], ...] = Field(max_length=500)

    @model_validator(mode="after")
    def rows_match_columns(self) -> "Table":
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("every row needs one value per column")
        return self


class Stat(Contract):
    """One headline value; ``change`` is the difference from the previous value."""

    label: str = Field(min_length=1, max_length=80)
    value: float | str
    unit: str = Field(default="", max_length=24)
    change: float | None = None


class Stats(Contract):
    """Shape: a few labeled headline values."""

    name: str = Field(min_length=1, max_length=120)
    items: tuple[Stat, ...] = Field(min_length=1, max_length=12)


class Chart(Contract):
    """View: lines or bars over time."""

    type: Literal["chart"] = "chart"
    title: str = Field(max_length=120)
    kind: Literal["line", "bar"] = "line"
    unit: str = Field(default="", max_length=24)
    y_log: bool = False
    series: tuple[Series, ...] = Field(min_length=1, max_length=12)


class TableView(Contract):
    """View: a table."""

    type: Literal["table"] = "table"
    title: str = Field(max_length=120)
    columns: tuple[Column, ...] = Field(min_length=1, max_length=12)
    rows: tuple[tuple[Cell, ...], ...] = Field(max_length=500)


class StatView(Contract):
    """View: a row of headline values."""

    type: Literal["stat"] = "stat"
    title: str = Field(max_length=120)
    items: tuple[Stat, ...] = Field(min_length=1, max_length=12)


View = Chart | TableView | StatView


class Block(Contract):
    """A visual in an answer: a view plus where its data came from.

    The view holds only values a source returned; the model chose the widget and
    its options. ``source_id`` and ``params`` are enough to fetch the data again
    without the model, at most every ``refresh_seconds`` when that is set.
    """

    widget: str
    evidence_ids: tuple[str, ...]
    source_id: str
    params: dict[str, JsonValue]
    options: dict[str, JsonValue]
    refresh_seconds: int | None = None
    view: Annotated[View, Field(discriminator="type")]
