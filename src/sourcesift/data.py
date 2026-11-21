"""Tables that sources return, and what a page can draw from them.

A source returns one or more ``Table`` values. A widget turns one table and
typed options into a *view*: a ``Figure`` (a Plotly figure), a ``TableView``, or
a ``StatView``. Sources and widgets never refer to each other, so any widget can
show any source's table whose columns fit its options.
"""

from typing import Annotated, Literal

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
        """What the model needs in order to choose a widget and its columns."""
        return {
            "table": self.name,
            "rows": len(self.rows),
            "columns": [
                {"name": c.name, "kind": self.kind(c.name)}
                | ({"unit": c.unit} if c.unit else {})
                for c in self.columns
            ],
        }


class Stat(Contract):
    """One headline value; ``change`` is the difference from the previous value."""

    label: str = Field(min_length=1, max_length=80)
    value: float | str
    unit: str = Field(default="", max_length=24)
    change: float | None = None


class Figure(Contract):
    """View: a Plotly figure, as the ``data`` and ``layout`` Plotly.js accepts.

    The interface applies its own colours and fonts. ``overlay`` asks it to add a
    layer it knows how to fetch; only maps use it.
    """

    type: Literal["figure"] = "figure"
    title: str = Field(max_length=120)
    data: tuple[dict[str, JsonValue], ...] = Field(min_length=1, max_length=24)
    layout: dict[str, JsonValue] = Field(default_factory=dict)
    overlay: Literal["none", "radar"] = "none"


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


View = Figure | TableView | StatView
VIEWS = (Figure, TableView, StatView)


class Block(Contract):
    """A visual in an answer: a view, and the table and evidence it came from.

    The view holds only values a source returned; the model chose the widget and
    its options. It is a snapshot of the data when it was retrieved.
    """

    widget: str
    evidence_ids: tuple[str, ...]
    source_id: str
    options: dict[str, JsonValue]
    table: Table
    view: Annotated[View, Field(discriminator="type")]
