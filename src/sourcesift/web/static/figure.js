// Draws a Plotly figure sent by the server, in the page's colours.
// The server decides what is plotted; this file decides only how it looks.
import { el } from "/dom.js";

const Plotly = window.Plotly;
const dark = window.matchMedia("(prefers-color-scheme: dark)");
const drawn = new Map(); // plot element -> { draw, view, radar }

// A report is a document on white paper, whatever the page's theme. These are
// the light values of the tokens in app.css.
const PAPER = {
  text: "#0b0b0b",
  secondary: "#52514e",
  muted: "#6f6e69",
  grid: "#e6e5e0",
  border: "#dcdbd5",
  surface: "#ffffff",
  accent: "#2a78d6",
  series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
};

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

function build(view, radar, paper = false) {
  const theme = paper ? PAPER : {
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
    paper_bgcolor: paper ? "#ffffff" : "rgba(0,0,0,0)",
    plot_bgcolor: paper ? "#ffffff" : "rgba(0,0,0,0)",
    font: { family: getComputedStyle(document.body).fontFamily, size: 12, color: theme.secondary },
    colorway: theme.series,
    margin: isMap ? { l: 0, r: 0, t: 0, b: 0 } : paper ? { l: 16, r: 16, t: 16, b: 16 } : { l: 8, r: 8, t: 8, b: 8 },
    legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { color: theme.secondary } },
    hoverlabel: { bgcolor: theme.surface, bordercolor: theme.border, font: { color: theme.text, size: 13 } },
    bargap: 0.3,
    barcornerradius: 4,
  };
  if (isMap) {
    layout.map = { ...given.map, style: dark.matches && !paper ? "carto-darkmatter" : "carto-positron" };
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
  drawn.set(plot, { draw, view, radar });
  try {
    await draw();
  } catch {
    container.replaceChildren(el("p", { class: "muted" }, "This visual could not be drawn."));
  }
}

/** A PNG of a drawn figure for a report, as a data URL, or null when it cannot be made. */
export async function figureImage(container) {
  const shown = drawn.get(container.querySelector(".figure"));
  if (!Plotly || !shown) return null;
  try {
    const { data, layout } = build(shown.view, shown.radar, true);
    return await Plotly.toImage({ data, layout: { ...layout, autosize: false } }, { format: "png", width: 900, height: layout.height, scale: 2 });
  } catch {
    return null;
  }
}

dark.addEventListener("change", () => {
  for (const [plot, shown] of drawn) {
    if (plot.isConnected) shown.draw(); else drawn.delete(plot);
  }
});
