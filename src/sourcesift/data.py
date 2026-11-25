"""Tables that sources return, and the figures drawn from them.

A source returns one or more ``Table`` values. A ``Figure`` is a chart of one
table: the columns and chart kind the model chose, with the rows the source
returned. The picture is drawn from that recipe by ``sourcesift.figures``, so a
figure's values never pass through the model.
"""

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
