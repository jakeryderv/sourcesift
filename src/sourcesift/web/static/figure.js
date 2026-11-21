// Draws a Plotly figure sent by the server, in the page's colours.
// The server decides what is plotted; this file decides only how it looks.
import { el } from "/dom.js";

const Plotly = window.Plotly;
const dark = window.matchMedia("(prefers-color-scheme: dark)");
const drawn = new Map(); // container -> redraw, for theme changes

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function axis(theme, given = {}) {
  return {
    gridcolor: theme.grid,
    linecolor: theme.border,
    zerolinecolor: theme.border,
    tickfont: { color: theme.muted },
    automargin: true,
    ...given,
    title: given.title ? { font: { color: theme.muted, size: 12 }, standoff: 8, ...given.title } : undefined,
  };
}

function build(view, radar) {
  const theme = {
    text: token("--text-primary"),
    secondary: token("--text-secondary"),
    muted: token("--text-muted"),
    grid: token("--grid"),
    border: token("--border"),
    surface: token("--surface-1"),
    accent: token("--accent"),
    series: Array.from({ length: 8 }, (_, i) => token(`--series-${i + 1}`)),
  };
  const isMap = view.data.some((trace) => trace.type === "scattermap");
  const given = view.layout ?? {};
  const layout = {
    ...given,
    autosize: true,
    height: given.height ?? (isMap ? 360 : 320),
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: getComputedStyle(document.body).fontFamily, size: 12, color: theme.secondary },
    colorway: theme.series,
    margin: isMap ? { l: 0, r: 0, t: 0, b: 0 } : { l: 8, r: 8, t: 8, b: 8 },
    legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { color: theme.secondary } },
    hoverlabel: { bgcolor: theme.surface, bordercolor: theme.border, font: { color: theme.text, size: 13 } },
    bargap: 0.3,
    barcornerradius: 4,
  };
  if (isMap) {
    layout.map = { ...given.map, style: dark.matches ? "carto-darkmatter" : "carto-positron" };
    if (radar) {
      // Radar imagery exists only at regional scale and wider.
      layout.map.layers = [{ sourcetype: "raster", source: [radar], below: "traces", opacity: 0.7, maxzoom: 7, sourceattribution: "Radar by RainViewer" }];
    }
  } else {
    layout.xaxis = axis(theme, given.xaxis);
    layout.yaxis = axis(theme, given.yaxis);
  }
  if (view.data.some((trace) => trace.type === "pie")) {
    layout.legend = { ...layout.legend, y: -0.05, yanchor: "top" };
  }
  const data = view.data.map((trace) => {
    if (trace.type === "scattermap") {
      return { ...trace, marker: { ...trace.marker, color: theme.accent }, textfont: { color: theme.text, size: 13 } };
    }
    if (trace.type === "pie") {
      return { ...trace, marker: { colors: theme.series, line: { color: theme.surface, width: 2 } }, textfont: { color: theme.text } };
    }
    if (trace.type === "scatter") return { ...trace, line: { width: 2, ...trace.line }, marker: { size: 8, ...trace.marker } };
    return trace;
  });
  return { data, layout };
}

/** Draw `view` into `container`. `radar` is a tile address, when the view asks for one. */
export async function renderFigure(container, view, radar) {
  if (!Plotly) {
    container.replaceChildren(el("p", { class: "muted" }, "The chart library did not load."));
    return;
  }
  const plot = el("div", { class: "figure" });
  container.replaceChildren(plot);
  const draw = () => {
    const { data, layout } = build(view, radar);
    const isMap = Boolean(layout.map);
    return Plotly.react(plot, data, layout, { displayModeBar: false, responsive: true, scrollZoom: isMap });
  };
  drawn.set(plot, draw);
  try {
    await draw();
  } catch {
    container.replaceChildren(el("p", { class: "muted" }, "This visual could not be drawn."));
  }
}

/** A PNG of a drawn figure as a data URL, or null when it cannot be made. */
export async function figureImage(container) {
  const plot = container.querySelector(".figure");
  if (!Plotly || !plot) return null;
  try {
    return await Plotly.toImage(plot, { format: "png", width: 900, height: plot.clientHeight * (900 / Math.max(plot.clientWidth, 1)), scale: 2 });
  } catch {
    return null;
  }
}

dark.addEventListener("change", () => {
  for (const [plot, draw] of drawn) {
    if (plot.isConnected) draw(); else drawn.delete(plot);
  }
});
