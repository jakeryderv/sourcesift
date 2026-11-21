// A small SVG line chart: one value axis, crosshair tooltip, keyboard access, table view.
const SVG = "http://www.w3.org/2000/svg";
const MAX_SERIES = 8;

export function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function svg(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 2 });
const exact = new Intl.NumberFormat("en", { maximumFractionDigits: 3 });

export function formatValue(value, unit = "", short = true) {
  if (typeof value !== "number") return String(value ?? "—");
  const text = (short ? compact : exact).format(Math.abs(value));
  const sign = value < 0 ? "−" : "";
  if (unit === "USD") return `${sign}$${text}`;
  if (unit === "%" || unit.startsWith("°")) return `${sign}${text}${unit}`;
  return unit ? `${sign}${text} ${unit}` : sign + text;
}

function niceTicks(min, max, count = 4) {
  if (min === max) { min -= 1; max += 1; }
  const raw = (max - min) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw);
  const ticks = [];
  for (let v = Math.floor(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(v);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function logTicks(min, max) {
  const ticks = [];
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e += 1) ticks.push(10 ** e);
  return ticks;
}

export function renderChart(container, view, tooltip) {
  const series = view.series.slice(0, MAX_SERIES).map((s) => ({
    name: s.name,
    points: s.points.map((p) => ({ t: Date.parse(p.at), v: p.value })),
  })).filter((s) => s.points.length);
  container.replaceChildren();
  container.classList.add("chart");
  if (!series.length) {
    container.append(el("p", { class: "muted" }, "No data to draw."));
    return;
  }
  if (series.length > 1) {
    const legend = el("div", { class: "legend" });
    series.forEach((s, i) => {
      const item = el("span");
      item.append(el("i", { class: `key s${i + 1}` }), document.createTextNode(s.name));
      legend.append(item);
    });
    container.append(legend);
  }
  const holder = el("div");
  container.append(holder);

  const times = [...new Set(series.flatMap((s) => s.points.map((p) => p.t)))].sort((a, b) => a - b);
  const lookup = series.map((s) => new Map(s.points.map((p) => [p.t, p.v])));
  const values = series.flatMap((s) => s.points.map((p) => p.v));
  const log = view.y_log && Math.min(...values) > 0;
  const ticks = log ? logTicks(Math.min(...values), Math.max(...values)) : niceTicks(Math.min(...values), Math.max(...values));
  const [lo, hi] = [ticks[0], ticks[ticks.length - 1]];
  const span = times[times.length - 1] - times[0];
  // Short spans are hourly data: label times in the zone the data is about.
  const timeZone = view.timezone || "UTC";
  const hourly = span < 12 * 864e5;
  const axisFormat = hourly ? { weekday: "short", hour: "numeric" } : span > 300 * 864e5 ? { month: "short", year: "numeric" } : { month: "short", day: "numeric" };
  const fullFormat = hourly ? { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" } : { dateStyle: "medium" };
  const dateLabel = new Intl.DateTimeFormat("en", { ...axisFormat, timeZone });
  const fullDate = new Intl.DateTimeFormat("en", { ...fullFormat, timeZone });
  let active = null;

  function draw() {
    const width = Math.max(holder.clientWidth, 320);
    const height = 280;
    const m = { top: 10, right: 70, bottom: 26, left: 58 };
    const x = (t) => m.left + (span ? (t - times[0]) / span : 0.5) * (width - m.left - m.right);
    const scale = log ? Math.log10 : (v) => v;
    const y = (v) => height - m.bottom - ((scale(v) - scale(lo)) / (scale(hi) - scale(lo))) * (height - m.top - m.bottom);
    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, height, role: "img", tabindex: "0", "aria-label": `${view.title}. Line chart of ${series.map((s) => s.name).join(", ")}. Use arrow keys to read values.` });

    for (const tick of ticks) {
      root.append(svg("line", { class: "gridline", x1: m.left, x2: width - m.right, y1: y(tick), y2: y(tick) }));
      root.append(svg("text", { x: m.left - 8, y: y(tick) + 4, "text-anchor": "end" }, formatValue(tick, view.unit)));
    }
    const steps = Math.min(5, times.length - 1) || 1;
    for (let i = 0; i <= steps; i += 1) {
      const t = times[0] + (span * i) / steps;
      root.append(svg("text", { x: x(t), y: height - 6, "text-anchor": i === 0 ? "start" : i === steps ? "end" : "middle" }, dateLabel.format(t)));
    }
    const placed = [];
    series.forEach((s, i) => {
      const path = s.points.map((p, n) => `${n ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
      root.append(svg("path", { class: `line s${i + 1}`, d: path }));
      const last = s.points[s.points.length - 1];
      root.append(svg("circle", { class: `dot f${i + 1}`, cx: x(last.t), cy: y(last.v), r: 4 }));
      // Label the line's end unless it would collide with one already placed.
      if (series.length <= 4 && placed.every((py) => Math.abs(py - y(last.v)) > 14)) {
        placed.push(y(last.v));
        root.append(svg("text", { class: "end", x: x(last.t) + 9, y: y(last.v) + 4 }, formatValue(last.v, view.unit)));
      }
    });

    const cross = svg("line", { class: "cross", y1: m.top, y2: height - m.bottom, visibility: "hidden" });
    const marks = series.map((_, i) => svg("circle", { class: `dot f${i + 1}`, r: 4, visibility: "hidden" }));
    const hit = svg("rect", { class: "hit", x: m.left, y: m.top, width: width - m.left - m.right, height: height - m.top - m.bottom });
    root.append(cross, ...marks, hit);

    function show(index, clientX, clientY) {
      active = Math.max(0, Math.min(times.length - 1, index));
      const t = times[active];
      cross.setAttribute("x1", x(t)); cross.setAttribute("x2", x(t));
      cross.setAttribute("visibility", "visible");
      tooltip.replaceChildren(el("div", { class: "when" }, fullDate.format(t)));
      series.forEach((s, i) => {
        const v = lookup[i].get(t);
        marks[i].setAttribute("visibility", v === undefined ? "hidden" : "visible");
        if (v === undefined) return;
        marks[i].setAttribute("cx", x(t)); marks[i].setAttribute("cy", y(v));
        const row = el("div", { class: "row" });
        row.append(el("i", { class: `key s${i + 1}` }), el("strong", {}, formatValue(v, view.unit)), el("span", { class: "name" }, s.name));
        tooltip.append(row);
      });
      tooltip.hidden = false;
      const box = root.getBoundingClientRect();
      const left = clientX ?? box.left + (x(t) / width) * box.width;
      const top = clientY ?? box.top + m.top;
      const w = tooltip.offsetWidth;
      tooltip.style.left = `${left + 14 + w > window.innerWidth ? left - w - 14 : left + 14}px`;
      tooltip.style.top = `${Math.max(8, top - 10)}px`;
    }
    function hide() {
      active = null;
      tooltip.hidden = true;
      cross.setAttribute("visibility", "hidden");
      marks.forEach((mark) => mark.setAttribute("visibility", "hidden"));
    }
    hit.addEventListener("pointermove", (event) => {
      const box = root.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * width;
      const t = times[0] + ((px - m.left) / (width - m.left - m.right)) * span;
      let nearest = 0;
      times.forEach((value, i) => { if (Math.abs(value - t) < Math.abs(times[nearest] - t)) nearest = i; });
      show(nearest, event.clientX, event.clientY);
    });
    hit.addEventListener("pointerleave", hide);
    root.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        show((active ?? times.length - 1) + (event.key === "ArrowLeft" ? -1 : 1));
      } else if (event.key === "Escape") hide();
    });
    root.addEventListener("blur", hide);
    holder.replaceChildren(root);
  }

  draw();
  let frame = 0;
  new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw); }).observe(holder);

  // The same values as a table, so nothing depends on hovering.
  const details = el("details", { class: "data-view" });
  details.append(el("summary", {}, "View data"));
  const table = el("table", { class: "data" });
  const head = el("tr");
  head.append(el("th", {}, "Date"), ...series.map((s) => el("th", { class: "num" }, s.name)));
  table.append(head);
  for (const t of [...times].reverse().slice(0, 400)) {
    const row = el("tr");
    row.append(el("td", {}, fullDate.format(t)), ...lookup.map((map) => el("td", { class: "num" }, map.has(t) ? formatValue(map.get(t), view.unit, false) : "—")));
    table.append(row);
  }
  const scroll = el("div", { class: "scroll" });
  scroll.append(table);
  details.append(scroll);
  if (view.series.length > MAX_SERIES) details.append(el("p", { class: "muted" }, `${view.series.length - MAX_SERIES} more series are not drawn.`));
  container.append(details);
}
