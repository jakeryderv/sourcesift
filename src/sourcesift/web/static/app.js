import { el, formatTime, formatValue } from "/dom.js";
import { renderFigure } from "/figure.js";

const $ = (id) => document.getElementById(id);
const transcript = $("transcript");
const scroller = $("scroller");
const state = { token: "", session: null, busy: false, abort: null, references: new Map(), sources: [], turns: 0, radar: null };

let toastTimer = 0;
function toast(text) {
  const node = $("toast");
  node.textContent = text;
  node.hidden = !text;
  clearTimeout(toastTimer);
  if (text) toastTimer = setTimeout(() => { node.hidden = true; }, 6000);
}

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

// Follow new content only while the reader is already at the bottom.
function nearBottom() { return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120; }
function follow(wasNear) { if (wasNear) scroller.scrollTop = scroller.scrollHeight; }

// ---- Answer text -------------------------------------------------------------

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
      fragment.append(el("button", { type: "button", class: "cite", "data-cite": part, title: state.references.get(part)?.title ?? part }, part.slice(1)));
    });
    node.replaceWith(fragment);
  }
  for (const link of root.querySelectorAll("a")) { link.target = "_blank"; link.rel = "noopener noreferrer"; }
}

function setAnswer(node, html) {
  // Rendered by the server with raw HTML escaped and images disabled.
  node.innerHTML = html;
  linkCitations(node);
}

function safeUrl(url) { return /^https?:\/\//i.test(url) ? url : null; }

function referenceItem(ref) {
  const item = el("div", { class: "item", "data-ref": ref.id });
  const url = safeUrl(ref.url);
  const title = url ? el("a", { class: "title", href: url, target: "_blank", rel: "noopener noreferrer" }, ref.title) : el("span", { class: "title" }, ref.title);
  const head = el("div");
  head.append(el("span", { class: "badge" }, ref.id.slice(1)), " ", title);
  const date = ref.published_at || ref.updated_at;
  const meta = [ref.publisher, ref.kind.replaceAll("_", " "), date ? `published ${date.slice(0, 10)}` : null, `retrieved ${ref.retrieved_at.slice(0, 16).replace("T", " ")} UTC`];
  item.append(head, el("div", { class: "meta" }, meta.filter(Boolean).join(" · ")));
  for (const note of ref.limitations) item.append(el("div", { class: "meta" }, `Note: ${note}`));
  return item;
}

// ---- Activity: what the agent is doing ---------------------------------------

function createActivity(timed = false) {
  const root = el("div", { class: "activity working open" });
  const head = el("button", { type: "button", class: "activity-head", "aria-expanded": "true" });
  const icon = el("span", { class: "spinner" });
  const text = el("span", { class: "activity-text" }, "Thinking…");
  head.append(icon, text, el("span", { class: "chevron" }, "›"));
  const list = el("div", { class: "steps" });
  root.append(head, list);
  head.addEventListener("click", () => head.setAttribute("aria-expanded", String(root.classList.toggle("open"))));
  const rows = new Map();
  const started = performance.now();

  function upsert(step) {
    let row = rows.get(step.id);
    if (!row) {
      row = el("div", { class: "step" });
      const rowHead = el("button", { type: "button", class: "step-head", "aria-expanded": "false" });
      rowHead.append(el("span"), el("span", { class: "step-title" }), el("span", { class: "step-summary" }));
      row.append(rowHead, el("div", { class: "step-lines" }));
      rowHead.addEventListener("click", () => rowHead.setAttribute("aria-expanded", String(row.classList.toggle("open"))));
      rows.set(step.id, row);
      list.append(row);
    }
    const [mark, title, summary] = row.firstChild.children;
    mark.className = step.state === "running" ? "spinner" : "mark";
    mark.textContent = step.state === "done" ? "✓" : step.state === "failed" ? "–" : "";
    title.textContent = step.title;
    summary.textContent = step.summary;
    row.lastChild.textContent = step.lines.join("\n") || "No further detail.";
  }

  return {
    root,
    status(value) { text.textContent = value; },
    step(step) {
      upsert(step);
      text.textContent = step.state === "running" ? `${step.title}…` : "Thinking…";
    },
    finish(steps, failed = false) {
      steps?.forEach(upsert);
      const seconds = Math.max(1, Math.round((performance.now() - started) / 1000));
      root.classList.remove("working", "open");
      head.setAttribute("aria-expanded", "false");
      icon.className = "mark";
      icon.textContent = failed ? "–" : "✓";
      const count = rows.size;
      const did = count ? `${count} step${count === 1 ? "" : "s"}` : "No lookups";
      // Only a turn watched live has a meaningful duration.
      text.textContent = timed ? `${did} · ${seconds}s` : did;
      if (!count) root.querySelector(".chevron")?.remove();
    },
  };
}

// ---- Visuals -----------------------------------------------------------------

// The address of the current radar imagery, looked up once per page load.
function radarTiles() {
  state.radar ??= api("/api/radar").then((response) => response.json()).then((data) => data.tiles, () => null);
  return state.radar;
}

function renderTable(body, view) {
  const table = el("table", { class: "data" });
  const head = el("tr");
  const numeric = view.columns.map((_, i) => view.rows.some((row) => typeof row[i] === "number"));
  view.columns.forEach((column, i) => head.append(el("th", numeric[i] ? { class: "num" } : {}, column.unit ? `${column.name} (${column.unit})` : column.name)));
  table.append(head);
  for (const row of view.rows) {
    const tr = el("tr");
    row.forEach((cell, i) => {
      const text = typeof cell === "number" ? formatValue(cell, "", false) : view.columns[i].kind === "time" ? formatTime(cell) : cell ?? "—";
      tr.append(el("td", numeric[i] ? { class: "num" } : {}, text));
    });
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

async function drawFigure(body, block) {
  const view = block.view;
  const radar = view.overlay === "radar" ? await radarTiles() : null;
  const plot = el("div");
  body.replaceChildren(plot);
  await renderFigure(plot, view, radar);
  if (view.overlay === "radar" && !radar) body.append(el("p", { class: "muted small" }, "Radar imagery is unavailable right now."));
  // The same values as a table, for reading exactly and for screen readers.
  const shown = { columns: block.table.columns, rows: block.table.rows.slice(0, 200) };
  const details = el("details", { class: "data-view" });
  const count = block.table.rows.length;
  details.append(el("summary", {}, count > 200 ? `View data (first 200 of ${count} rows)` : "View data"));
  const holder = el("div");
  renderTable(holder, shown);
  details.append(holder);
  body.append(details);
}

function drawView(body, block) {
  if (block.view.type === "figure") drawFigure(body, block);
  else if (block.view.type === "table") renderTable(body, block.view);
  else renderStats(body, block.view);
}

// One card for all of an answer's visuals: figures first, then maps, charts, tables.
function rank(view) {
  if (view.type === "stat") return 0;
  if (view.type === "table") return 3;
  return view.data.some((trace) => trace.type === "scattermap") ? 1 : 2;
}

function renderArtifact(blocks) {
  const card = el("section", { class: "artifact" });
  const head = el("div", { class: "artifact-head" });
  const names = [...new Set(blocks.map((b) => state.sources.find((s) => s.id === b.source_id)?.name ?? b.source_id))];
  head.append(el("strong", {}, names.join(" · ")));
  for (const id of [...new Set(blocks.flatMap((b) => b.evidence_ids))].slice(0, 4)) head.append(el("button", { type: "button", class: "cite", "data-cite": id }, id.slice(1)));
  card.append(head);
  for (const block of [...blocks].sort((a, b) => rank(a.view) - rank(b.view))) {
    const section = el("div", { class: "widget" });
    const body = el("div");
    section.append(el("h4", {}, block.view.title), body);
    card.append(section);
    drawView(body, block);
  }
  return card;
}

// ---- Turns -------------------------------------------------------------------

function fillTurn(node, turn, index) {
  const result = turn.result;
  for (const ref of result.references) state.references.set(ref.id, ref);
  if (result.blocks.length) node.append(renderArtifact(result.blocks));
  const answer = el("div", { class: "answer" });
  setAnswer(answer, turn.answer_html);
  node.append(answer);

  const foot = el("div", { class: "turn-foot" });
  const meta = el("div", { class: "meta-body" });
  const count = result.references.length;
  const notes = result.limitations.length;
  if (count || notes) {
    const label = [count ? `${count} source${count === 1 ? "" : "s"}` : null, notes ? `${notes} note${notes === 1 ? "" : "s"}` : null].filter(Boolean).join(" · ");
    const toggle = el("button", { type: "button", class: "ghost", "aria-expanded": "false" }, label);
    toggle.addEventListener("click", () => toggle.setAttribute("aria-expanded", String(meta.classList.toggle("open"))));
    foot.append(toggle);
    for (const ref of result.references) meta.append(referenceItem(ref));
    if (notes) {
      const list = el("ul", { class: "notes" });
      for (const note of result.limitations) list.append(el("li", {}, note));
      meta.append(list);
    }
  }
  const copy = el("button", { type: "button", class: "ghost" }, "Copy");
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(result.answer); toast("Answer copied"); } catch { toast("Copying is not available here."); }
  });
  const save = el("button", { type: "button", class: "ghost" }, "Save report");
  save.addEventListener("click", async () => {
    try {
      const data = await (await api(`/api/sessions/${state.session}/report`, { method: "POST", body: { turn: index } })).json();
      toast(`Report saved to ${data.path}`);
    } catch (error) { toast(error.message); }
  });
  foot.append(copy, save);
  node.append(foot, meta);
}

function renderTurn(turn) {
  $("empty")?.remove();
  const node = el("article", { class: "turn" });
  node.append(el("div", { class: "question" }, turn.prompt));
  const activity = createActivity();
  activity.finish(turn.result.steps);
  if (turn.result.steps.length) node.append(activity.root);
  fillTurn(node, turn, state.turns);
  state.turns += 1;
  transcript.append(node);
}

function setBusy(busy) {
  state.busy = busy;
  $("send").classList.toggle("busy", busy);
  $("send").setAttribute("aria-label", busy ? "Stop" : "Send");
}

async function send(prompt) {
  if (state.busy || !prompt.trim()) return;
  $("empty")?.remove();
  toast("");
  setBusy(true);
  state.abort = new AbortController();
  const node = el("article", { class: "turn" });
  const activity = createActivity(true);
  const draft = el("div", { class: "answer streaming" });
  node.append(el("div", { class: "question" }, prompt), activity.root, draft);
  transcript.append(node);
  scroller.scrollTop = scroller.scrollHeight;
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
        const wasNear = nearBottom();
        if (event.event === "status") activity.status(event.text);
        else if (event.event === "step") activity.step(event.step);
        else if (event.event === "draft") { activity.status("Writing…"); setAnswer(draft, event.html); }
        else if (event.event === "reset") draft.replaceChildren();
        else if (event.event === "result") {
          draft.remove();
          activity.finish(event.turn.result.steps);
          fillTurn(node, event.turn, state.turns);
          state.turns += 1;
          finished = true;
        } else if (event.event === "error") throw new Error(event.message);
        follow(wasNear);
      }
    }
    if (!finished) throw new Error("The connection closed before the answer finished.");
  } catch (error) {
    draft.remove();
    activity.finish(null, true);
    node.append(el("div", { class: "error" }, error.name === "AbortError" ? "Stopped." : error.message));
  } finally {
    setBusy(false);
    state.abort = null;
  }
}

// ---- Side panel --------------------------------------------------------------

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
        toast(`${enabled.length} of ${state.sources.length} sources enabled for this chat`);
      } catch (error) { toast(error.message); }
    });
  });
}

// ---- Startup and input -------------------------------------------------------

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
  data.turns.forEach(renderTurn);
  scroller.scrollTop = scroller.scrollHeight;
}

const input = $("prompt");
function resize() { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 200)}px`; }
function submit() {
  const prompt = input.value;
  if (state.busy || !prompt.trim()) return;
  input.value = "";
  resize();
  send(prompt);
}
input.addEventListener("input", resize);
$("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.busy) state.abort?.abort(); else submit();
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); }
});
document.addEventListener("click", (event) => {
  const chip = event.target.closest("[data-cite]");
  if (chip) showEvidence(chip.dataset.cite);
  const suggestion = event.target.closest(".suggestion");
  if (suggestion) send(suggestion.textContent);
});
$("btn-sources").addEventListener("click", showSources);
$("btn-evidence").addEventListener("click", () => showEvidence());
$("panel-close").addEventListener("click", () => { $("panel").hidden = true; });
$("btn-new").addEventListener("click", () => {
  if (state.busy) { toast("Stop the running answer before starting a new chat."); return; }
  remember("session", null);
  location.reload();
});

// The launch link carries the token in its fragment, which is never sent to a server.
const fromLink = location.hash.slice(1);
if (fromLink) {
  remember("token", fromLink);
  history.replaceState(null, "", location.pathname);
}
state.token = fromLink || recall("token") || "";
openSession().then(() => input.focus(), (error) => {
  $("empty")?.replaceChildren(el("h2", {}, "Not connected"), el("p", { class: "muted" }, error.message));
  $("send").disabled = true;
});
