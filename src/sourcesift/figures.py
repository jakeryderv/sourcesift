"""Draw a figure's picture from its recipe and rows.

Every interface gets a figure's image from ``render_png``, so a chart looks the
same in the web app, in a saved artifact, and from the SDK. Drawing needs no
display, browser, or network.
"""

import io
import math
from dataclasses import dataclass
from functools import lru_cache

from sourcesift.data import Cell, Figure, FigureKind, Table, _moment

MAX_BARS = 60
MAX_PARTS = 12
MAX_SERIES = 8
MAX_LABEL = 48  # characters of a category name beside a bar
# Eight series colours that stay distinct in print and for common colour blindness.
PALETTE = (
    "#3b6fb6",
    "#d9822b",
    "#3d9970",
    "#c0504d",
    "#7e62a3",
    "#8c6d4f",
    "#d47fb1",
    "#6b7480",
)
_INK = "#1f2933"
_GRID = "#d9dee4"


def _short(text: str) -> str:
    return text if len(text) <= MAX_LABEL else text[: MAX_LABEL - 1] + "…"


def _numbers(table: Table, name: str) -> list[float | None]:
    if table.kind(name) != "number":
        raise ValueError(f"Column {name!r} is not numeric.")
    return [
        float(cell) if isinstance(cell, int | float) else None
        for cell in table.values(name)
    ]


@dataclass(frozen=True)
class _Plan:
    """Validated data for one chart: named series over shared positions."""

    kind: FigureKind
    x_kind: str
    series: dict[str, tuple[list[Cell], list[float | None]]]
    categories: list[str]
    unit: str
    x_unit: str
    log_scale: bool


def _plan(figure: Figure) -> _Plan:
    table, kind = figure.table, figure.kind
    if not table.rows:
        raise ValueError("The table has no rows to plot.")
    x_kind = table.kind(figure.x)
    xs = table.values(figure.x)
    columns = {name: _numbers(table, name) for name in figure.y}
    if kind in {"line", "area", "scatter"} and x_kind == "text":
        raise ValueError(
            f"A {kind} chart needs a time or number column for x; {figure.x!r} is "
            "text. Use bar for categories."
        )
    keep = [i for i, x in enumerate(xs) if x is not None]
    if not keep:
        raise ValueError("The table has no rows to plot.")
    if x_kind == "time":
        for i in keep:
            _moment(xs[i], figure.x)
    series: dict[str, tuple[list[Cell], list[float | None]]] = {}
    if kind == "donut":
        values = [columns[figure.y[0]][i] or 0.0 for i in keep]
        if len(keep) > MAX_PARTS or any(value < 0 for value in values):
            raise ValueError(
                f"A donut needs at most {MAX_PARTS} rows of non-negative values; "
                "use bar instead."
            )
        if not any(values):
            raise ValueError("A donut needs at least one value above zero.")
        series[figure.y[0]] = ([xs[i] for i in keep], list(values))
    elif figure.series:
        if len(figure.y) != 1:
            raise ValueError("Use series with exactly one y column.")
        groups = table.values(figure.series)
        ys = columns[figure.y[0]]
        for i in keep:
            group = series.setdefault(str(groups[i]), ([], []))
            group[0].append(xs[i])
            group[1].append(ys[i])
        if len(series) > MAX_SERIES:
            raise ValueError(
                f"{figure.series!r} has {len(series)} values; a chart can show "
                f"{MAX_SERIES} series."
            )
    else:
        for name in figure.y:
            series[name] = ([xs[i] for i in keep], [columns[name][i] for i in keep])
    categories = list(dict.fromkeys(str(xs[i]) for i in keep))
    if kind in {"bar", "stacked_bar"} and len(categories) > MAX_BARS:
        raise ValueError(f"More than {MAX_BARS} bars; use a line chart.")
    units = {table.columns[table.index(name)].unit for name in figure.y}
    plotted = [v for _, values in series.values() for v in values if v is not None]
    if not plotted:
        raise ValueError("Those columns have no values to plot.")
    return _Plan(
        kind=kind,
        x_kind=x_kind,
        series=series,
        categories=categories,
        unit=units.pop() if len(units) == 1 else "",
        x_unit=table.columns[table.index(figure.x)].unit,
        log_scale=figure.log_scale and min(plotted) > 0,
    )


def check_figure(figure: Figure) -> None:
    """Raise ``ValueError`` with a message for the model when the recipe cannot be drawn."""
    _plan(figure)


def _compact(value: float) -> str:
    """A tick value as people write large numbers: 38.1T, 2.5M, 1,200."""
    size = abs(value)
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if size >= limit:
            return f"{value / limit:,.4g}{suffix}"
    return f"{value:,.10g}"


def _label_axis(axis, unit: str) -> None:
    from matplotlib.ticker import FuncFormatter

    if unit in {"USD", "$"}:
        axis.set_major_formatter(FuncFormatter(lambda value, _: f"${_compact(value)}"))
    elif unit == "%" or unit.startswith("°"):
        axis.set_major_formatter(
            FuncFormatter(lambda value, _: f"{_compact(value)}{unit}")
        )
    else:
        axis.set_major_formatter(FuncFormatter(lambda value, _: _compact(value)))
        if unit:
            axis.set_label_text(unit, color=_INK)


def _positions(plan: _Plan, across: list[Cell], name: str) -> list:
    if plan.x_kind == "time":
        return [_moment(x, name) for x in across]
    return [float(x) if isinstance(x, int | float) else math.nan for x in across]


def _gaps(values: list[float | None]) -> list[float]:
    return [math.nan if value is None else value for value in values]


def _draw(figure: Figure, plan: _Plan):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure as Canvas

    bars = plan.kind in {"bar", "stacked_bar"}
    sideways = bars and plan.x_kind == "text"
    height = max(4.5, 1.2 + 0.32 * len(plan.categories)) if sideways else 4.5
    canvas = Canvas(figsize=(8, min(height, 20)), facecolor="white")
    FigureCanvasAgg(canvas)
    axes = canvas.add_subplot()
    axes.set_title(figure.title, loc="left", color=_INK, fontsize=13, pad=12)
    names = list(plan.series)
    if plan.kind == "donut":
        across, values = plan.series[names[0]]
        axes.pie(
            [value or 0.0 for value in values],
            labels=None,
            colors=[PALETTE[i % len(PALETTE)] for i in range(len(values))],
            autopct=lambda share: f"{share:.0f}%" if share >= 4 else "",
            pctdistance=0.78,
            startangle=90,
            counterclock=False,
            wedgeprops={"width": 0.45, "edgecolor": "white"},
            textprops={"color": "white", "fontsize": 9},
        )
        axes.legend(
            [_short(str(x)) for x in across],
            loc="center left",
            bbox_to_anchor=(1.0, 0.5),
            frameon=False,
        )
        axes.set_aspect("equal")
        return canvas
    if bars:
        slots = {category: i for i, category in enumerate(plan.categories)}
        stacked = plan.kind == "stacked_bar"
        width = 0.8 if stacked else 0.8 / len(names)
        floor = [0.0] * len(slots)
        for n, name in enumerate(names):
            across, values = plan.series[name]
            heights = [0.0] * len(slots)
            for x, value in zip(across, values, strict=True):
                heights[slots[str(x)]] += value or 0.0
            where = [
                i if stacked else i - 0.4 + width * (n + 0.5) for i in range(len(slots))
            ]
            colour = PALETTE[n % len(PALETTE)]
            if sideways:
                axes.barh(
                    where,
                    heights,
                    height=width,
                    left=floor if stacked else None,
                    color=colour,
                    label=name,
                )
            else:
                axes.bar(
                    where,
                    heights,
                    width=width,
                    bottom=floor if stacked else None,
                    color=colour,
                    label=name,
                )
            if stacked:
                floor = [a + b for a, b in zip(floor, heights, strict=True)]
        labels = [_short(category) for category in plan.categories]
        ticks = list(range(len(slots)))
        if sideways:
            axes.set_yticks(ticks, labels)
            # The first row goes at the top, as in the table.
            axes.invert_yaxis()
        else:
            crowded = len(labels) > 8 or max(map(len, labels)) > 10
            axes.set_xticks(
                ticks,
                labels,
                rotation=45 if crowded else 0,
                ha="right" if crowded else "center",
            )
    else:
        floor_line: list[float] | None = None
        for n, name in enumerate(names):
            across, values = plan.series[name]
            where = _positions(plan, across, figure.x)
            colour = PALETTE[n % len(PALETTE)]
            if plan.kind == "scatter":
                axes.scatter(where, _gaps(values), color=colour, label=name, s=28)
            elif plan.kind == "area":
                top = [value or 0.0 for value in values]
                # Series stack when they share the same positions.
                if floor_line is not None and len(floor_line) == len(top):
                    top = [a + b for a, b in zip(floor_line, top, strict=True)]
                    base = floor_line
                else:
                    base = [0.0] * len(top)
                axes.fill_between(
                    where, base, top, color=colour, alpha=0.75, label=name
                )
                floor_line = top
            else:
                axes.plot(where, _gaps(values), color=colour, label=name, linewidth=2)
        if plan.x_kind == "time":
            canvas.autofmt_xdate(rotation=30, ha="right")
        else:
            _label_axis(axes.xaxis, plan.x_unit)
    value_axis = axes.xaxis if sideways else axes.yaxis
    _label_axis(value_axis, plan.unit)
    if plan.log_scale:
        (axes.set_xscale if sideways else axes.set_yscale)("log")
    axes.grid(True, axis="x" if sideways else "y", color=_GRID, linewidth=0.8)
    axes.set_axisbelow(True)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(_GRID)
    axes.tick_params(colors=_INK, labelsize=9)
    if len(names) > 1:
        axes.legend(frameon=False, fontsize=9)
    return canvas


@lru_cache(maxsize=64)
def _png(figure: Figure, dpi: int) -> bytes:
    canvas = _draw(figure, _plan(figure))
    buffer = io.BytesIO()
    canvas.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight")
    return buffer.getvalue()


def render_png(figure: Figure, *, dpi: int = 144) -> bytes:
    """Return the figure as a PNG image on a white background.

    Raises ``ValueError`` when the recipe does not fit its table; a figure made
    by the agent has already passed that check.
    """
    return _png(figure, dpi)
