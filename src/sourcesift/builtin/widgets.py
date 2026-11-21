"""Built-in widgets. Each draws any source's table whose columns fit its options."""

from typing import Literal

from pydantic import Field, JsonValue

from sourcesift.contract import Contract
from sourcesift.data import Cell, Figure, Stat, StatView, Table, TableView
from sourcesift.extend import widget

MAX_BARS = 60
MAX_PARTS = 12
MAX_SERIES = 8  # the interface has eight series colours
MAX_PLACES = 200
MAX_LABEL = 48  # characters of a category name beside a bar


def with_unit(value: float, unit: str) -> str:
    """A value and its unit as people write them: 38°F, 45%, 12 mph."""
    text = f"{value:,.10g}"
    if unit in {"USD", "$"}:
        return f"${text}"
    return text + (unit if unit == "%" or unit.startswith("°") else f" {unit}".rstrip())


class TitleOptions(Contract):
    """A heading for the visual."""

    title: str = Field(
        default="", max_length=80, description="Heading; defaults to the table's name."
    )


def _short(text: str) -> str:
    return text if len(text) <= MAX_LABEL else text[: MAX_LABEL - 1] + "…"


def _numbers(table: Table, name: str) -> list[float | None]:
    if table.kind(name) != "number":
        raise ValueError(f"Column {name!r} is not numeric.")
    return [
        float(cell) if isinstance(cell, int | float) else None
        for cell in table.values(name)
    ]


def _axis(unit: str) -> dict[str, JsonValue]:
    if unit in {"USD", "$"}:
        return {"tickprefix": "$"}
    if unit == "%" or unit.startswith("°"):
        return {"ticksuffix": unit}
    return {"title": {"text": unit}} if unit else {}


class ChartOptions(TitleOptions):
    kind: Literal["line", "area", "bar", "stacked_bar", "scatter", "donut"] = Field(
        default="line",
        description="line or area: numbers over a time or number column. bar or "
        "stacked_bar: numbers across categories. scatter: how two numbers relate. "
        "donut: parts of a whole, for a dozen rows at most.",
    )
    x: str = Field(
        description="Column for the horizontal axis; for donut, the column that "
        "names each part."
    )
    y: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_SERIES,
        description="Numeric columns to plot, one series each. donut uses the first.",
    )
    series: str = Field(
        default="",
        description="Optional text column that splits a single y column into one "
        "series per value.",
    )
    log_scale: bool = Field(
        default=False, description="Logarithmic value axis; positive values only."
    )


@widget(
    id="chart",
    description="A line, area, bar, stacked bar, scatter, or donut chart of a "
    "table's columns.",
    options=ChartOptions,
)
def chart(table: Table, options: ChartOptions) -> Figure:
    kind = options.kind
    x_kind = table.kind(options.x)
    xs = table.values(options.x)
    columns = {name: _numbers(table, name) for name in options.y}
    if kind in {"line", "area", "scatter"} and x_kind == "text":
        raise ValueError(
            f"A {kind} chart needs a time or number column for x; {options.x!r} is "
            "text. Use bar for categories."
        )
    keep = [i for i, x in enumerate(xs) if x is not None]
    if not keep:
        raise ValueError("The table has no rows to plot.")
    title = options.title or table.name
    if kind == "donut":
        values = [columns[options.y[0]][i] or 0.0 for i in keep]
        if len(keep) > MAX_PARTS or any(value < 0 for value in values):
            raise ValueError(
                f"A donut needs at most {MAX_PARTS} rows of non-negative values; "
                "use bar instead."
            )
        names = [str(xs[i]) for i in keep]
        # Names go in the legend, shortened; the slice shows its share.
        part: dict[str, JsonValue] = {
            "type": "pie",
            "hole": 0.55,
            "labels": [_short(name) for name in names],
            "values": list(values),
            "textinfo": "percent",
            "sort": False,
            "hovertext": list(names),
            "hovertemplate": "%{hovertext}: %{value} (%{percent})<extra></extra>",
        }
        return Figure(title=title, data=(part,), layout={"showlegend": True})

    # name -> (x values, y values)
    series: dict[str, tuple[list[Cell], list[float | None]]] = {}
    if options.series:
        if len(options.y) != 1:
            raise ValueError("Use series with exactly one y column.")
        groups = table.values(options.series)
        ys = columns[options.y[0]]
        for i in keep:
            group = series.setdefault(str(groups[i]), ([], []))
            group[0].append(xs[i])
            group[1].append(ys[i])
        if len(series) > MAX_SERIES:
            raise ValueError(
                f"{options.series!r} has {len(series)} values; a chart can show "
                f"{MAX_SERIES} series. Use a table instead."
            )
    else:
        for name in options.y:
            series[name] = ([xs[i] for i in keep], [columns[name][i] for i in keep])
    bars = kind in {"bar", "stacked_bar"}
    if bars and len({x for x in xs if x is not None}) > MAX_BARS:
        raise ValueError(f"More than {MAX_BARS} bars; use a table or a line chart.")
    # Named categories read better down the side than slanted under the bars.
    sideways = bars and x_kind == "text"
    base: dict[str, JsonValue] = (
        {"type": "bar"}
        if bars
        else {"type": "scatter", "mode": "markers" if kind == "scatter" else "lines"}
    )
    if kind == "area":
        base["stackgroup"] = "one"
    traces: list[dict[str, JsonValue]] = []
    for name, (across, up) in series.items():
        trace: dict[str, JsonValue] = {
            **base,
            "name": name,
            "x": list(across),
            "y": list(up),
        }
        if sideways:
            labels: list[JsonValue] = [str(x) for x in across]
            short: list[JsonValue] = [_short(str(x)) for x in across]
            trace["orientation"] = "h"
            trace["x"] = list(up)
            trace["y"] = short
            trace["customdata"] = labels
            trace["hovertemplate"] = "%{customdata}: %{x}<extra></extra>"
        traces.append(trace)
    units = {table.columns[table.index(name)].unit for name in options.y}
    value_axis = _axis(units.pop()) if len(units) == 1 else {}
    plotted = [v for _, values in series.values() for v in values if v is not None]
    if options.log_scale and plotted and min(plotted) > 0:
        value_axis["type"] = "log"
    category_axis: dict[str, JsonValue] = {}
    if x_kind == "time":
        category_axis["type"] = "date"
    elif bars:
        category_axis["type"] = "category"
    elif x_unit := table.columns[table.index(options.x)].unit:
        category_axis = _axis(x_unit)
    layout: dict[str, JsonValue] = {"showlegend": len(traces) > 1}
    if sideways:
        count = len({x for x in xs if x is not None})
        # The first row goes at the top, as in the table.
        layout |= {
            "xaxis": value_axis,
            "yaxis": category_axis | {"autorange": "reversed"},
            "height": max(220, 60 + 30 * count),
        }
    else:
        layout |= {"xaxis": category_axis, "yaxis": value_axis}
        if kind != "scatter":
            layout["hovermode"] = "x unified"
    if bars:
        layout["barmode"] = "stack" if kind == "stacked_bar" else "group"
    return Figure(title=title, data=tuple(traces), layout=layout)


class TableOptions(TitleOptions):
    columns: tuple[str, ...] = Field(
        default=(), max_length=12, description="Columns to show; empty shows all."
    )
    max_rows: int = Field(default=20, ge=1, le=100, description="Rows to show.")


@widget(
    id="table",
    description="Rows and columns, in the order the source returned them.",
    options=TableOptions,
)
def table(data: Table, options: TableOptions) -> TableView:
    picked = [data.index(name) for name in options.columns] or range(len(data.columns))
    return TableView(
        title=options.title or data.name,
        columns=tuple(data.columns[i] for i in picked),
        rows=tuple(
            tuple(row[i] for i in picked) for row in data.rows[: options.max_rows]
        ),
    )


class StatOptions(TitleOptions):
    columns: tuple[str, ...] = Field(
        default=(),
        max_length=12,
        description="Columns to show as figures; empty shows every numeric column.",
    )
    row: Literal["first", "last"] = Field(
        default="last",
        description="Which row to read. With 'last', each figure also shows its "
        "change from the row before.",
    )


@widget(
    id="stats",
    description="Headline figures: the values of one row, one figure per column.",
    options=StatOptions,
)
def stats(data: Table, options: StatOptions) -> StatView:
    if not data.rows:
        raise ValueError("The table has no rows.")
    names = options.columns or tuple(
        c.name for c in data.columns if data.kind(c.name) == "number"
    )
    row = data.rows[-1 if options.row == "last" else 0]
    before = data.rows[-2] if options.row == "last" and len(data.rows) > 1 else None
    items = []
    for name in names:
        position = data.index(name)
        value = row[position]
        if value is None:
            continue
        earlier = before[position] if before else None
        numeric = isinstance(value, int | float) and isinstance(earlier, int | float)
        items.append(
            Stat(
                label=name,
                value=value,
                unit=data.columns[position].unit,
                change=value - earlier if numeric else None,
            )
        )
    if not items:
        raise ValueError("That row has no values in those columns.")
    return StatView(title=options.title or data.name, items=tuple(items[:12]))


class MapOptions(TitleOptions):
    latitude: str = Field(
        default="", description="Latitude column; found by name when left empty."
    )
    longitude: str = Field(
        default="", description="Longitude column; found by name when left empty."
    )
    label: str = Field(
        default="", description="Column naming each place; the first text column "
        "when left empty."
    )  # fmt: skip
    value: str = Field(
        default="", description="Optional numeric column to show beside each label."
    )
    zoom: int = Field(
        default=6, ge=2, le=12, description="3 is a continent, 6 a region, 10 a city."
    )
    overlay: Literal["none", "radar"] = Field(
        default="none",
        description="'radar' adds current precipitation radar; use it for weather. "
        "Radar is drawn at zoom 6 and wider.",
    )


def _named(table: Table, wanted: str, names: tuple[str, ...]) -> str:
    if wanted:
        return wanted
    for column in table.columns:
        if column.name.casefold() in names:
            return column.name
    raise ValueError(f"This table has no {names[0]} column, so it cannot be mapped.")


@widget(
    id="map",
    description="Places on a map, from a table with latitude and longitude "
    "columns, optionally under current precipitation radar.",
    options=MapOptions,
)
def place_map(data: Table, options: MapOptions) -> Figure:
    lats = _numbers(data, _named(data, options.latitude, ("latitude", "lat")))
    lons = _numbers(
        data, _named(data, options.longitude, ("longitude", "lon", "lng", "long"))
    )
    label = options.label or next(
        (c.name for c in data.columns if data.kind(c.name) == "text"), ""
    )
    labels = data.values(label) if label else [None] * len(data.rows)
    values = _numbers(data, options.value) if options.value else None
    unit = data.columns[data.index(options.value)].unit if options.value else ""
    places: list[tuple[float, float, str]] = []
    for i, (lat, lon) in enumerate(zip(lats, lons, strict=True)):
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        text = str(labels[i]) if labels[i] is not None else ""
        if values is not None and (value := values[i]) is not None:
            text = f"{text} · {with_unit(value, unit)}".removeprefix(" · ")
        places.append((lat, lon, text))
    if not places or len(places) > MAX_PLACES:
        raise ValueError(f"A map needs between 1 and {MAX_PLACES} located rows.")
    trace: dict[str, JsonValue] = {
        "type": "scattermap",
        "mode": "markers+text" if len(places) <= 12 else "markers",
        "lat": [p[0] for p in places],
        "lon": [p[1] for p in places],
        "text": [p[2] for p in places],
        "textposition": "top right",
        "hoverinfo": "text",
        "marker": {"size": 12},
    }
    radar = options.overlay == "radar"
    layout: dict[str, JsonValue] = {
        "map": {
            "center": {
                "lat": sum(p[0] for p in places) / len(places),
                "lon": sum(p[1] for p in places) / len(places),
            },
            # Radar imagery stops at a regional scale.
            "zoom": min(options.zoom, 6) if radar else options.zoom,
        },
        "showlegend": False,
    }
    return Figure(
        title=options.title or data.name,
        data=(trace,),
        layout=layout,
        overlay=options.overlay,
    )
