// Small helpers shared by the page's modules.

export function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 2 });
const exact = new Intl.NumberFormat("en", { maximumFractionDigits: 3 });
const day = new Intl.DateTimeFormat("en", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
const moment = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "UTC" });

export function formatValue(value, unit = "", short = true) {
  if (typeof value !== "number") return String(value ?? "—");
  const text = (short ? compact : exact).format(Math.abs(value));
  const sign = value < 0 ? "−" : "";
  if (unit === "USD") return `${sign}$${text}`;
  if (unit === "%" || unit.startsWith("°")) return `${sign}${text}${unit}`;
  return unit ? `${sign}${text} ${unit}` : sign + text;
}

// Times arrive as ISO text already in the zone they should be read in, so they
// are formatted as written, without converting to the viewer's zone.
export function formatTime(value) {
  const text = String(value ?? "");
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(text);
  const parsed = new Date(dateOnly ? `${text}T00:00:00Z` : `${text.slice(0, 16)}:00Z`);
  if (Number.isNaN(parsed.getTime())) return text || "—";
  return (dateOnly ? day : moment).format(parsed);
}
