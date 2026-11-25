// Small helpers shared by the page's modules.

export function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

const day = new Intl.DateTimeFormat("en", { month: "short", day: "numeric" });
const clock = new Intl.DateTimeFormat("en", { hour: "numeric", minute: "2-digit" });

// When something last changed, as a reader would say it: a time today, else a date.
export function formatWhen(value) {
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return "";
  const today = new Date().toDateString() === moment.toDateString();
  return (today ? clock : day).format(moment);
}
