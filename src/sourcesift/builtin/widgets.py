"""Built-in widgets. Each accepts one data shape, whatever source it came from."""

from typing import Literal

from pydantic import Field

from sourcesift.contract import Contract
from sourcesift.data import (
    Chart,
    GeoPoints,
    MapView,
    Stats,
    StatView,
    Table,
    TableView,
    TimeSeries,
)
from sourcesift.extend import widget


class TitleOptions(Contract):
    """A heading for the visual."""

    title: str = Field(
        default="", max_length=80, description="Heading; defaults to the data's name."
    )


class LineOptions(TitleOptions):
    log_scale: bool = Field(
        default=False, description="Logarithmic value axis; positive values only."
    )


class TableOptions(TitleOptions):
    max_rows: int = Field(default=20, ge=1, le=100, description="Rows to show.")


@widget(
    id="line-chart",
    description="Values over time as lines, one per series.",
    accepts=TimeSeries,
    options=LineOptions,
)
def line_chart(data: TimeSeries, options: LineOptions) -> Chart:
    positive = all(p.value > 0 for s in data.series for p in s.points)
    return Chart(
        title=options.title or data.name,
        unit=data.unit,
        timezone=data.timezone,
        y_log=options.log_scale and positive,
        series=data.series,
    )


@widget(
    id="table",
    description="Rows and columns, in the order the source returned them.",
    accepts=Table,
    options=TableOptions,
)
def table(data: Table, options: TableOptions) -> TableView:
    return TableView(
        title=options.title or data.name,
        columns=data.columns,
        rows=data.rows[: options.max_rows],
    )


@widget(
    id="stats",
    description="A few headline figures, each with its change from the previous value.",
    accepts=Stats,
    options=TitleOptions,
)
def stats(data: Stats, options: TitleOptions) -> StatView:
    return StatView(title=options.title or data.name, items=data.items)


class MapOptions(TitleOptions):
    zoom: int = Field(
        default=7, ge=3, le=11, description="3 is a continent, 7 a region, 11 a city."
    )
    overlay: Literal["none", "radar"] = Field(
        default="none",
        description="'radar' adds a live precipitation radar layer; use it for weather.",
    )


@widget(
    id="map",
    description="Places on a map, optionally under live precipitation radar.",
    accepts=GeoPoints,
    options=MapOptions,
)
def place_map(data: GeoPoints, options: MapOptions) -> MapView:
    count = len(data.points)
    return MapView(
        title=options.title or data.name,
        latitude=sum(p.latitude for p in data.points) / count,
        longitude=sum(p.longitude for p in data.points) / count,
        zoom=options.zoom,
        markers=data.points,
        overlay=options.overlay,
    )
