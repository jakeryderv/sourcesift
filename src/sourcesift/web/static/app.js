import { el, formatWhen } from "/dom.js";

const $ = (id) => document.getElementById(id);
const transcript = $("transcript");
const scroller = $("scroller");
const state = {
  token: "",
  session: null,
  saving: false,
  formats: [],
  busy: false,
  abort: null,
  references: new Map(),
  sources: [],
  artifacts: [],
  turns: 0,
  panel: null,
  shown: null,
};

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
const sessionPath = (rest = "") => `/api/sessions/${encodeURIComponent(state.session)}${rest}`;

// Follow new content only while the reader is already at the bottom.
function nearBottom() { return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120; }
function follow(wasNear) { if (wasNear) scroller.scrollTop = scroller.scrollHeight; }

// ---- Rendered text -----------------------------------------------------------

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

function setRendered(node, html) {
  // Rendered by the server: raw HTML escaped, and only figures as images.
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

function flash(body, id) {
  const target = id && body.querySelector(`[data-ref="${CSS.escape(id)}"]`);
  if (!target) return;
  target.classList.add("flash");
  target.scrollIntoView({ block: "center" });
  setTimeout(() => target.classList.remove("flash"), 1600);
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

// ---- Side panel: evidence, sources, or an artifact ----------------------------

function openPanel(kind, title, build) {
  state.panel = kind;
  const panel = $("panel");
  panel.className = kind === "artifact" ? "wide" : "";
  $("panel-title").textContent = title;
  $("panel-actions").replaceChildren();
  const body = $("panel-body");
  body.replaceChildren();
  build(body, $("panel-actions"));
  panel.hidden = false;
}

function closePanel() {
  state.panel = null;
  state.shown = null;
  $("panel").hidden = true;
}

function showEvidence(focus) {
  openPanel("evidence", "Evidence", (body) => {
    const refs = [...state.references.values()].sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
    if (!refs.length) body.append(el("p", { class: "muted" }, "No evidence yet. Cited sources appear here."));
    for (const ref of refs) body.append(referenceItem(ref));
    flash(body, focus);
  });
}

function showSources() {
  openPanel("sources", "Sources for this chat", (body) => {
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
        const data = await (await api(sessionPath("/sources"), { method: "PUT", body: { enabled } })).json();
        state.sources = data.sources;
        toast(`${enabled.length} of ${state.sources.length} sources enabled for this chat`);
      } catch (error) { toast(error.message); }
    });
  });
}

async function download(artifact, format) {
  const response = await api(sessionPath(`/artifacts/${artifact.id}/download?format=${format}`));
  const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? `${artifact.id}.${format}`;
  const url = URL.createObjectURL(await response.blob());
  const link = el("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function setArtifacts(artifacts) {
  state.artifacts = artifacts;
  const button = $("btn-artifacts");
  button.hidden = !artifacts.length;
  button.textContent = artifacts.length > 1 ? `Artifacts (${artifacts.length})` : "Artifact";
  // Keep an open artifact current after a revision.
  if (state.panel === "artifact") showArtifact(state.shown);
}

function showArtifact(id) {
  const artifact = state.artifacts.find((item) => item.id === id) ?? state.artifacts.at(-1);
  if (!artifact) { closePanel(); return; }
  state.shown = artifact.id;
  openPanel("artifact", artifact.title, (body, tools) => {
    if (state.artifacts.length > 1) {
      const pick = el("select", { "aria-label": "Choose an artifact" });
      for (const item of state.artifacts) {
        const option = el("option", { value: item.id }, item.title);
        option.selected = item.id === artifact.id;
        pick.append(option);
      }
      pick.addEventListener("change", () => showArtifact(pick.value));
      tools.append(pick);
    }
    const act = async (button, work) => {
      button.disabled = true;
      try { await work(); } catch (error) { toast(error.message); }
      button.disabled = false;
    };
    const copy = el("button", { type: "button", class: "ghost" }, "Copy");
    copy.title = "Copy the Markdown";
    copy.addEventListener("click", () => act(copy, async () => {
      await navigator.clipboard.writeText(artifact.markdown);
      toast("Markdown copied");
    }));
    const save = el("button", { type: "button", class: "ghost" }, "Download");
    save.title = "A zip with the Quarto file, its references, and its figures";
    save.addEventListener("click", () => act(save, () => download(artifact, "zip")));
    tools.append(copy, save);
    if (state.formats.length) {
      const pick = el("select", { "aria-label": "Export with Quarto" });
      pick.append(el("option", { value: "" }, "Export as…"));
      for (const format of state.formats) pick.append(el("option", { value: format.id }, format.label));
      pick.addEventListener("change", () => {
        const format = pick.value;
        pick.value = "";
        if (!format) return;
        toast("Exporting…");
        act(pick, async () => { await download(artifact, format); toast("Exported"); });
      });
      tools.append(pick);
    }

    const meta = [`Version ${artifact.version}`, `updated ${formatWhen(artifact.updated_at)}`];
    body.append(el("p", { class: "muted small" }, meta.join(" · ")));
    const page = el("article", { class: "answer document" });
    setRendered(page, artifact.html);
    body.append(page);
    if (artifact.notes.length) {
      const notes = el("ul", { class: "notes" });
      for (const note of artifact.notes) notes.append(el("li", {}, note));
      body.append(el("h3", { class: "section" }, "Notes"), notes);
    }
    const cited = [...new Set([...page.querySelectorAll("[data-cite]")].map((chip) => chip.dataset.cite))];
    const refs = cited.map((key) => state.references.get(key)).filter(Boolean);
    if (refs.length) {
      body.append(el("h3", { class: "section" }, "References"));
      for (const ref of refs) body.append(referenceItem(ref));
    }
  });
}

// ---- Turns -------------------------------------------------------------------

function fillTurn(node, turn, index) {
  const result = turn.result;
  for (const ref of result.references) state.references.set(ref.id, ref);
  const answer = el("div", { class: "answer" });
  setRendered(answer, turn.answer_html);
  node.append(answer);
  for (const artifact of result.artifacts) {
    const card = el("button", { type: "button", class: "artifact-card", "data-artifact": artifact.id });
    card.append(el("span", { class: "artifact-kind" }, artifact.version > 1 ? "Revised artifact" : "Artifact"), el("strong", {}, artifact.title), el("span", { class: "muted" }, "Open"));
    node.append(card);
  }

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
  foot.append(copy);
  if (!result.artifacts.length) {
    const keep = el("button", { type: "button", class: "ghost" }, "Keep as artifact");
    keep.addEventListener("click", async () => {
      keep.disabled = true;
      try {
        const data = await (await api(sessionPath("/artifacts"), { method: "POST", body: { turn: index } })).json();
        setArtifacts(data.artifacts);
        showArtifact(data.id);
        refreshConversations();
      } catch (error) { toast(error.message); keep.disabled = false; }
    });
    foot.append(keep);
  }
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
    const response = await api(sessionPath("/turns"), { method: "POST", body: { prompt }, signal: state.abort.signal });
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
        else if (event.event === "draft") { activity.status("Writing…"); setRendered(draft, event.html); }
        else if (event.event === "reset") draft.replaceChildren();
        else if (event.event === "result") {
          draft.remove();
          activity.finish(event.turn.result.steps);
          fillTurn(node, event.turn, state.turns);
          state.turns += 1;
          finished = true;
          $("title").textContent = event.title || "New chat";
          setArtifacts(event.artifacts);
          const written = event.turn.result.artifacts.at(-1);
          if (written) showArtifact(written.id);
          if (event.save_error) toast(event.save_error);
          refreshConversations();
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

// ---- Conversations -----------------------------------------------------------

function remember(key, value) {
  try {
    if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, value);
  } catch { /* storage unavailable: the page still works until reloaded */ }
}
function recall(key) { try { return sessionStorage.getItem(key); } catch { return null; } }

function showConversation(data) {
  state.session = data.id;
  remember("session", data.id);
  state.sources = data.sources;
  state.references = new Map();
  state.turns = 0;
  closePanel();
  $("title").textContent = data.title || "New chat";
  $("model").textContent = data.model || "no model selected";
  transcript.replaceChildren();
  if (data.turns.length) data.turns.forEach(renderTurn);
  else transcript.append($("empty-state").content.cloneNode(true));
  setArtifacts(data.artifacts);
  scroller.scrollTop = scroller.scrollHeight;
  markCurrent();
  $("prompt").focus();
}

async function openConversation(body) {
  if (state.busy) { toast("Stop the running answer before switching chats."); return; }
  try {
    showConversation(await (await api("/api/sessions", { method: "POST", body })).json());
    document.body.classList.remove("side-open");
  } catch (error) { toast(error.message); }
}

function markCurrent() {
  for (const row of $("conversations").children) row.classList.toggle("current", row.dataset.id === state.session);
}

function conversationRow(item) {
  const row = el("div", { class: "conversation", "data-id": item.id });
  const open = el("button", { type: "button", class: "conversation-open" });
  const detail = [formatWhen(item.updated_at), item.artifacts ? `${item.artifacts} artifact${item.artifacts === 1 ? "" : "s"}` : null];
  open.append(el("span", { class: "conversation-title" }, item.title || "Untitled"), el("span", { class: "conversation-meta" }, detail.filter(Boolean).join(" · ")));
  open.addEventListener("click", () => openConversation({ conversation: item.id }));
  const rename = el("button", { type: "button", class: "ghost row-tool", "aria-label": "Rename" }, "Rename");
  const remove = el("button", { type: "button", class: "ghost row-tool", "aria-label": "Delete" }, "Delete");
  rename.addEventListener("click", () => {
    const field = el("input", { type: "text", class: "rename", value: item.title, maxlength: "120", "aria-label": "Conversation name" });
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      const title = field.value.trim();
      if (save && title && title !== item.title) {
        try {
          await api(`/api/sessions/${encodeURIComponent(item.id)}`, { method: "PATCH", body: { title } });
          if (item.id === state.session) $("title").textContent = title;
        } catch (error) { toast(error.message); }
      }
      refreshConversations();
    };
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); finish(true); }
      if (event.key === "Escape") finish(false);
    });
    field.addEventListener("blur", () => finish(true));
    open.replaceWith(field);
    field.focus();
    field.select();
  });
  // Deleting asks once more in place, because it removes the saved files.
  remove.addEventListener("click", async () => {
    if (!remove.classList.contains("confirm")) {
      remove.classList.add("confirm");
      remove.textContent = "Delete forever?";
      setTimeout(() => { remove.classList.remove("confirm"); remove.textContent = "Delete"; }, 4000);
      return;
    }
    if (item.id === state.session && state.busy) { toast("Stop the running answer before deleting."); return; }
    try {
      await api(`/api/sessions/${encodeURIComponent(item.id)}`, { method: "DELETE" });
      if (item.id === state.session) await openConversation({});
      refreshConversations();
    } catch (error) { toast(error.message); }
  });
  row.append(open, rename, remove);
  return row;
}

async function refreshConversations() {
  if (!state.saving) return;
  try {
    const data = await (await api("/api/conversations")).json();
    $("conversations").replaceChildren(...data.conversations.map(conversationRow));
    $("side-note").hidden = data.conversations.length > 0;
    $("side-note").textContent = "Saved chats appear here.";
    markCurrent();
  } catch (error) { toast(error.message); }
}

// Reopen this tab's conversation after a reload, or start one.
async function start() {
  const info = await (await api("/api/info")).json();
  state.saving = info.saving;
  state.formats = info.export_formats;
  if (!state.saving) {
    $("side-note").hidden = false;
    $("side-note").textContent = "Chats are kept in memory only (started with --no-save).";
  }
  let data = null;
  const known = recall("session");
  if (known) {
    try { data = await (await api(`/api/sessions/${encodeURIComponent(known)}`)).json(); } catch { data = null; }
  }
  data ??= await (await api("/api/sessions", { method: "POST", body: { resume: true } })).json();
  showConversation(data);
  await refreshConversations();
}

// ---- Input -------------------------------------------------------------------

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
  // Inside an artifact a citation points at that artifact's own reference list.
  if (chip?.closest("#panel")) flash($("panel-body"), chip.dataset.cite);
  else if (chip) showEvidence(chip.dataset.cite);
  const card = event.target.closest("[data-artifact]");
  if (card) showArtifact(card.dataset.artifact);
  const suggestion = event.target.closest(".suggestion");
  if (suggestion) send(suggestion.textContent);
});
$("btn-sources").addEventListener("click", showSources);
$("btn-evidence").addEventListener("click", () => showEvidence());
$("btn-artifacts").addEventListener("click", () => showArtifact(state.shown));
$("panel-close").addEventListener("click", closePanel);
$("btn-new").addEventListener("click", () => openConversation({}));
$("btn-side").addEventListener("click", () => document.body.classList.toggle("side-open"));

// The launch link carries the token in its fragment, which is never sent to a server.
const fromLink = location.hash.slice(1);
if (fromLink) {
  remember("token", fromLink);
  history.replaceState(null, "", location.pathname);
}
state.token = fromLink || recall("token") || "";
start().catch((error) => {
  transcript.replaceChildren(el("div", { class: "empty" }));
  transcript.firstChild.append(el("h2", {}, "Not connected"), el("p", { class: "muted" }, error.message));
  $("send").disabled = true;
});
