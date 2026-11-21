import { el, formatValue, renderChart } from "/chart.js";
import { renderMap } from "/map.js";

const $ = (id) => document.getElementById(id);
const transcript = $("transcript");
const tooltip = $("tooltip");
const state = { token: "", session: null, busy: false, abort: null, references: new Map(), timers: [], sources: [] };

function status(text) { $("status").textContent = text; }

async function api(path, { method = "GET", body, signal } = {}) {
  const response = await fetch(path, {
    method,
    signal,
    headers: { Authorization: `Bearer ${state.token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try { message = (await response.json()).error || message; } catch { /* keep the default */ }
    throw new Error(message);
  }
  return response;
}

// ---- Rendering -------------------------------------------------------------

function linkCitations(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    if (!walker.currentNode.parentElement.closest("code, pre, a")) nodes.push(walker.currentNode);
  }
  for (const node of nodes) {
    const parts = node.textContent.split(/\[(S\d+)\]/);
    if (parts.length === 1) continue;
    const fragment = document.createDocumentFragment();
    parts.forEach((part, i) => {
      if (i % 2 === 0) { if (part) fragment.append(part); return; }
      const chip = el("button", { type: "button", class: "cite", "data-cite": part, title: state.references.get(part)?.title ?? part }, part);
      fragment.append(chip);
    });
    node.replaceWith(fragment);
  }
  for (const link of root.querySelectorAll("a")) { link.target = "_blank"; link.rel = "noopener noreferrer"; }
}

function safeUrl(url) { return /^https?:\/\//i.test(url) ? url : null; }

function referenceItem(ref) {
  const item = el("div", { class: "item", "data-ref": ref.id });
  const url = safeUrl(ref.url);
  const title = url ? el("a", { class: "title", href: url, target: "_blank", rel: "noopener noreferrer" }, ref.title) : el("span", { class: "title" }, ref.title);
  const head = el("div");
  head.append(el("span", { class: "badge" }, ref.id), " ", title);
  const date = ref.published_at || ref.updated_at;
  const meta = [ref.publisher, ref.kind.replaceAll("_", " "), date ? `published ${date.slice(0, 10)}` : "date unknown", `retrieved ${ref.retrieved_at.slice(0, 16).replace("T", " ")} UTC`];
  item.append(head, el("div", { class: "meta" }, meta.join(" · ")));
  for (const note of ref.limitations) item.append(el("div", { class: "meta" }, `Note: ${note}`));
  return item;
}

function renderTable(body, view) {
  const table = el("table", { class: "data" });
  const head = el("tr");
  const numeric = view.columns.map((_, i) => view.rows.some((row) => typeof row[i] === "number"));
  view.columns.forEach((column, i) => head.append(el("th", numeric[i] ? { class: "num" } : {}, column.unit ? `${column.name} (${column.unit})` : column.name)));
  table.append(head);
  for (const row of view.rows) {
    const tr = el("tr");
    row.forEach((cell, i) => tr.append(el("td", numeric[i] ? { class: "num" } : {}, typeof cell === "number" ? formatValue(cell, "", false) : cell ?? "—")));
    table.append(tr);
  }
  const scroll = el("div", { class: "scroll" });
  scroll.append(table);
  body.replaceChildren(scroll);
}

function renderStats(body, view) {
  const grid = el("div", { class: "stats" });
  for (const item of view.items) {
    const tile = el("div");
    tile.append(el("div", { class: "stat-label" }, item.label), el("div", { class: "stat-value" }, formatValue(item.value, item.unit)));
    if (typeof item.change === "number") {
      const arrow = item.change > 0 ? "▲" : item.change < 0 ? "▼" : "•";
      tile.append(el("div", { class: "stat-change" }, `${arrow} ${formatValue(Math.abs(item.change), item.unit)} since the previous value`));
    }
    grid.append(tile);
  }
  body.replaceChildren(grid);
}

async function loadTile(layer, z, x, y) {
  const response = await api(`/api/tiles/${layer}/${z}/${x}/${y}`);
  return URL.createObjectURL(await response.blob());
}

function drawView(body, view) {
  if (view.type === "chart") renderChart(body, view, tooltip);
  else if (view.type === "map") renderMap(body, view, loadTile);
  else if (view.type === "table") renderTable(body, view);
  else renderStats(body, view);
}

function renderBlock(block) {
  const card = el("section", { class: "block" });
  const head = el("div", { class: "block-head" });
  head.append(el("h3", {}, block.view.title));
  const body = el("div");
  const foot = el("div", { class: "block-foot" });
  foot.append("Data from");
  for (const id of block.evidence_ids.slice(0, 3)) foot.append(el("button", { type: "button", class: "cite", "data-cite": id }, id));
  if (block.evidence_ids.length > 3) foot.append(`and ${block.evidence_ids.length - 3} more`);
  card.append(head, body, foot);
  drawView(body, block.view);
  if (block.refresh_seconds) {
    const live = el("span", { class: "live" }, "Live");
    foot.append(el("span", { class: "grow" }), live);
    const timer = setInterval(async () => {
      if (document.visibilityState !== "visible" || !card.isConnected) return;
      try {
        const data = await (await api("/api/blocks/refresh", { method: "POST", body: { block } })).json();
        head.firstChild.textContent = data.block.view.title;
        drawView(body, data.block.view);
        live.textContent = `Live · updated ${new Date(data.refreshed_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
      } catch (error) {
        live.textContent = `Live · ${error.message}`;
      }
    }, block.refresh_seconds * 1000);
    state.timers.push(timer);
  }
  return card;
}

function renderTurn(turn) {
  $("empty")?.remove();
  const result = turn.result;
  for (const ref of result.references) state.references.set(ref.id, ref);
  const node = el("article", { class: "turn" });
  const answer = el("div", { class: "answer" });
  // Rendered by the server with raw HTML escaped and images disabled.
  answer.innerHTML = turn.answer_html;
  linkCitations(answer);
  node.append(el("div", { class: "question" }, turn.prompt), answer);
  for (const block of result.blocks) node.append(renderBlock(block));
  if (result.references.length) {
    const refs = el("details", { class: "refs" });
    refs.append(el("summary", {}, `${result.references.length} reference${result.references.length === 1 ? "" : "s"}`));
    for (const ref of result.references) refs.append(referenceItem(ref));
    node.append(refs);
  }
  if (result.limitations.length) {
    const notes = el("ul", { class: "notes" });
    for (const note of result.limitations) notes.append(el("li", {}, note));
    node.append(notes);
  }
  transcript.append(node);
  node.scrollIntoView({ block: "start", behavior: "smooth" });
}

// ---- Side panel ------------------------------------------------------------

function openPanel(title, build) {
  $("panel-title").textContent = title;
  const body = $("panel-body");
  body.replaceChildren();
  build(body);
  $("panel").hidden = false;
}

function showEvidence(focus) {
  openPanel("Evidence", (body) => {
    const refs = [...state.references.values()].sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
    if (!refs.length) body.append(el("p", { class: "muted" }, "No evidence yet. Cited sources appear here."));
    for (const ref of refs) body.append(referenceItem(ref));
    const target = focus && body.querySelector(`[data-ref="${CSS.escape(focus)}"]`);
    if (target) {
      target.classList.add("flash");
      target.scrollIntoView({ block: "center" });
    }
  });
}

function showSources() {
  openPanel("Sources for this chat", (body) => {
    const actions = el("div", { class: "panel-actions" });
    const all = el("button", { type: "button" }, "All");
    const none = el("button", { type: "button" }, "None");
    const apply = el("button", { type: "button", class: "primary" }, "Apply");
    actions.append(all, none, el("span", { class: "grow" }), apply);
    body.append(actions);
    const boxes = [];
    for (const source of state.sources) {
      const item = el("div", { class: "item" });
      const label = el("label");
      const box = el("input", { type: "checkbox", value: source.id });
      box.checked = source.enabled;
      boxes.push(box);
      const text = el("span");
      text.append(el("span", { class: "title" }, source.name), " ", el("span", { class: "badge" }, source.kind), el("div", { class: "meta" }, source.description));
      label.append(box, text);
      item.append(label);
      body.append(item);
    }
    all.addEventListener("click", () => boxes.forEach((box) => { box.checked = true; }));
    none.addEventListener("click", () => boxes.forEach((box) => { box.checked = false; }));
    apply.addEventListener("click", async () => {
      try {
        const enabled = boxes.filter((box) => box.checked).map((box) => box.value);
        const data = await (await api(`/api/sessions/${state.session}/sources`, { method: "PUT", body: { enabled } })).json();
        state.sources = data.sources;
        status(`${enabled.length} of ${state.sources.length} sources enabled for this chat`);
      } catch (error) { status(error.message); }
    });
  });
}

// ---- Conversation ----------------------------------------------------------

function remember(key, value) {
  try {
    if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, value);
  } catch { /* storage unavailable: the page still works until reloaded */ }
}
function recall(key) { try { return sessionStorage.getItem(key); } catch { return null; } }

// Reopen this tab's conversation after a reload, or start one.
async function openSession() {
  let data = null;
  const known = recall("session");
  if (known) {
    try { data = await (await api(`/api/sessions/${encodeURIComponent(known)}`)).json(); } catch { data = null; }
  }
  data ??= await (await api("/api/sessions", { method: "POST", body: { resume: true } })).json();
  state.session = data.id;
  remember("session", data.id);
  state.sources = data.sources;
  $("model").textContent = data.model || "no model selected";
  for (const node of [...transcript.children]) if (node.id !== "empty") node.remove();
  data.turns.forEach(renderTurn);
  status("");
}

function setBusy(busy) {
  state.busy = busy;
  $("send").textContent = busy ? "Stop" : "Send";
}

async function send(prompt) {
  if (state.busy || !prompt.trim()) return;
  $("empty")?.remove();
  setBusy(true);
  state.abort = new AbortController();
  const pending = el("article", { class: "turn" });
  const draft = el("div", { class: "draft" });
  pending.append(el("div", { class: "question" }, prompt), draft);
  transcript.append(pending);
  pending.scrollIntoView({ block: "start", behavior: "smooth" });
  status("Thinking…");
  try {
    const response = await api(`/api/sessions/${state.session}/turns`, { method: "POST", body: { prompt }, signal: state.abort.signal });
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    let finished = false;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines.filter(Boolean)) {
        const event = JSON.parse(line);
        if (event.event === "status") status(event.text);
        else if (event.event === "draft") draft.textContent += event.text;
        else if (event.event === "reset") draft.textContent = "";
        else if (event.event === "result") { pending.remove(); renderTurn(event.turn); status(""); finished = true; }
        else if (event.event === "error") throw new Error(event.message);
      }
    }
    if (!finished) throw new Error("The connection closed before the answer finished.");
    $("prompt").value = "";
  } catch (error) {
    draft.remove();
    const stopped = error.name === "AbortError";
    pending.append(el("div", { class: "error" }, stopped ? "Stopped." : error.message));
    status("");
  } finally {
    setBusy(false);
    state.abort = null;
  }
}

$("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.busy) state.abort?.abort();
  else send($("prompt").value);
});
$("prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!state.busy) send($("prompt").value);
  }
});
document.addEventListener("click", (event) => {
  const chip = event.target.closest("[data-cite]");
  if (chip) showEvidence(chip.dataset.cite);
  const suggestion = event.target.closest(".suggestion");
  if (suggestion) { $("prompt").value = suggestion.textContent; send(suggestion.textContent); }
});
$("btn-sources").addEventListener("click", showSources);
$("btn-evidence").addEventListener("click", () => showEvidence());
$("panel-close").addEventListener("click", () => { $("panel").hidden = true; });
$("btn-new").addEventListener("click", () => {
  if (state.busy) { status("Stop the running answer before starting a new chat."); return; }
  remember("session", null);
  location.reload();
});
$("btn-report").addEventListener("click", async () => {
  try {
    const data = await (await api(`/api/sessions/${state.session}/report`, { method: "POST", body: {} })).json();
    status(`Report saved to ${data.path}`);
  } catch (error) { status(error.message); }
});

// The launch link carries the token in its fragment, which is never sent to a server.
const fromLink = location.hash.slice(1);
if (fromLink) {
  remember("token", fromLink);
  history.replaceState(null, "", location.pathname);
}
state.token = fromLink || recall("token") || "";
openSession().catch((error) => {
  $("empty")?.replaceChildren(el("h2", {}, "Not connected"), el("p", { class: "muted" }, error.message));
  $("send").disabled = true;
});
