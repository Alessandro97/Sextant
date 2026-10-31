"use strict";

/* A thrown error in this file used to be invisible: the page rendered, the
   button did nothing, and the only symptom was "doesn't work". Surface it. */
function showCrash(what) {
  const box = document.getElementById("crash");
  if (!box) return;
  box.hidden = false;
  box.textContent = `Sextant hit an error — please send me this line:\n${what}`;
}
window.addEventListener("error", (e) =>
  showCrash(`${e.message}  (${(e.filename || "").split("/").pop()}:${e.lineno})`));
window.addEventListener("unhandledrejection", (e) =>
  showCrash(String((e.reason && e.reason.stack) || e.reason)));

const state = { path: null, ws: null, selected: null,
                assessTimer: null, assessRetry: null, scores: {},
                markerScores: {}, passages: {} };

const $ = (id) => document.getElementById(id);
const say = (t) => { $("status").textContent = t || ""; };

/** What each status means to a reader.
 *
 *  The internal names describe the mechanism -- "no-claim" says the sentence
 *  carried no number to screen -- which reads as a verdict on the citation
 *  when it is nothing of the kind. */
const STATUS_LABEL = {
  "verified":  "figure verified",
  "not-found": "figure missing",
  "no-source": "paper missing",
  "no-claim":  "not quantified",
};
const label_for = (status) => STATUS_LABEL[status] || status;

/** The same, for a count of several: "3 figure verified" read as a typo. */
const STATUS_LABEL_PLURAL = {
  "verified":  "figures verified",
  "not-found": "figures missing",
  "no-source": "papers missing",
};

/** Full-window spinner for work the reader must wait on. */
function busy(what, detail) {
  $("busy-what").textContent = what;
  $("busy-detail").textContent = detail || "";
  $("busy").classList.add("on");
}
function idle() { $("busy").classList.remove("on"); }

/** A spinner to drop into a container while something loads. */
function spinner(label, small) {
  const wrap = el("div", "inline-load");
  wrap.appendChild(el("div", small ? "spinner small" : "spinner"));
  if (label) wrap.appendChild(el("span", null, label));
  return wrap;
}
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

/** How much of a cited paper the model is given, per citation.
 *
 *  The three differ by roughly ten times in cost: a manuscript with thirty
 *  citations is about 13,000 tokens to assess at low and 350,000 at high. It
 *  is remembered, because it is a standing preference about spend, not a
 *  per-click decision.
 */
const EFFORTS = ["low", "mid", "high"];

function effort() {
  const saved = localStorage.getItem("sextant.effort");
  return EFFORTS.includes(saved) ? saved : "mid";
}

function setEffort(level) {
  localStorage.setItem("sextant.effort", level);
  paintEffort();
  paintAssessAll();
}

function paintEffort() {
  const now = effort();
  for (const button of document.querySelectorAll("#effort button")) {
    button.setAttribute("aria-pressed", String(button.dataset.effort === now));
  }
}

/** Name the manuscript over the manuscript.
 *
 *  The bar ellipsises a long name -- and they are long, being filenames --
 *  so the whole one has to stay reachable on hover. */
function setManuscriptName(name) {
  const node = $("filename");
  node.textContent = name || "";
  node.title = name || "";
}

async function get(url) {
  const response = await fetch(url);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

/* ------------------------------------------------------------------ open */

async function uploadFile(file) {
  if (!file) return;
  busy("Reading the PDF…", file.name);
  say("uploading…");
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/upload", { method: "POST", body: form });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    idle();
    say("");
    showReaderError(data.detail || `upload failed (${response.status})`);
    return;
  }
  idle();
  setManuscriptName(data.name);
  // A dropped file has no folder of its own -- a browser sends bytes and a
  // filename, never a path -- so its library sits beside Sextant's copy. The
  // setup step shows that plainly and lets it be changed before anything runs.
  await chooseManuscript(data.path);
}

/** Open a manuscript already on disk.
 *
 *  This is the path worth preferring when the file is local: the library is
 *  built in refs/ NEXT TO the manuscript, which is where anyone would look for
 *  it and where they will drop papers. Upload cannot do that -- a browser
 *  sends bytes and a filename, never a path -- so it has to relocate the
 *  library under the store, and two papers were lost to that.
 */
/* ---------------------------------------------- choosing by real path */

/** Browse the machine the server runs on.
 *
 *  A browser file picker cannot say where a file lives -- it hands over bytes
 *  and a filename, by design. So a manuscript chosen that way has no folder,
 *  and its library has to go somewhere invented. This asks the server, which
 *  is on the same machine, and yields a real path: the manuscript's own folder
 *  becomes the root and refs/ sits beside it.
 */
async function openBrowser(startAt) {
  $("browser").hidden = false;
  renderShortcuts();
  await listFolder(startAt || localStorage.getItem("sextant.browseAt") || null);
}

/** Somewhere to start other than the home directory.
 *  Clicking down from home to a project folder is three or four steps every
 *  time, and there was no way to paste a path you already knew. */
function renderShortcuts() {
  const bar = $("browse-shortcuts");
  bar.innerHTML = "";
  const recent = JSON.parse(localStorage.getItem("sextant.recentDirs") || "[]");
  const places = [["Home", null], ...recent.map((d) => [d.split("/").pop() || d, d])];
  for (const [name, dir] of places.slice(0, 6)) {
    const b = el("button", null, name);
    b.type = "button";
    b.title = dir || "your home directory";
    b.onclick = () => listFolder(dir);
    bar.appendChild(b);
  }
}

function rememberDir(dir) {
  const recent = JSON.parse(localStorage.getItem("sextant.recentDirs") || "[]");
  const next = [dir, ...recent.filter((d) => d !== dir)].slice(0, 5);
  localStorage.setItem("sextant.recentDirs", JSON.stringify(next));
}

/** Paste a folder to jump to it, or a PDF to open it directly. */
async function jumpToTyped(event) {
  event.preventDefault();
  const typed = $("browse-path").value.trim();
  if (!typed) return;
  if (typed.toLowerCase().endsWith(".pdf")) {
    await chooseManuscript(typed);
    return;
  }
  await listFolder(typed);
}

async function listFolder(dir) {
  const list = $("browse-list");
  list.innerHTML = "";
  list.appendChild(el("li", "up", "loading…"));

  let data;
  try {
    data = await get("/api/browse" + (dir ? `?dir=${encodeURIComponent(dir)}` : ""));
  } catch (err) {
    list.innerHTML = "";
    list.appendChild(el("li", "up", `${err.message} — check the path and try again`));
    return;
  }

  localStorage.setItem("sextant.browseAt", data.dir);
  rememberDir(data.dir);
  renderShortcuts();
  $("browse-where").textContent = data.dir;
  $("browse-path").value = data.dir;
  list.innerHTML = "";

  if (data.parent) {
    const up = el("li", "up", "⬑ up a level");
    up.onclick = () => listFolder(data.parent);
    list.appendChild(up);
  }
  if (!data.entries.length) {
    list.appendChild(el("li", "up", "(no folders or PDFs here)"));
  }
  for (const entry of data.entries) {
    const li = el("li", entry.kind === "dir" ? "dir" : "pdf",
                  (entry.kind === "dir" ? "📁 " : "📄 ") + entry.name);
    li.onclick = () => (entry.kind === "dir"
      ? listFolder(entry.path)
      : chooseManuscript(entry.path));
    list.appendChild(li);
  }
}

/** Picking a manuscript proposes a library and waits.
 *
 *  Nothing is read and nothing is created until Go. Where the library lives
 *  is the decision that has already gone wrong twice, so it is shown before
 *  it is acted on rather than discovered afterwards.
 */
async function chooseManuscript(chosen, { reopening = false } = {}) {
  $("browser").hidden = true;
  // Reached from the Library panel, this is a manuscript already on screen
  // being pointed at a different folder -- not an opening. The card says so,
  // and Back returns to the reader rather than to the file browser.
  state.reopening = reopening;
  $("setup-what").textContent = reopening ? "References folder" : "Ready to open";
  // A different manuscript must not inherit the last one's scores; keys like
  // "[4]" or "23501" recur across papers and would silently carry over.
  state.scores = {};
  state.markerScores = {};
  state.path = chosen;
  $("path").value = chosen;
  setManuscriptName(chosen.split("/").pop());
  localStorage.setItem("sextant.path", chosen);

  let proposed = chosen.replace(/\/[^/]*$/, "") + "/refs";
  let exists = false;
  try {
    const answer = await postJSON("/api/workspace/library", { path: chosen });
    proposed = answer.refs_dir;
    exists = answer.exists;
  } catch {
    /* keep the guess above; Go will report any real problem */
  }
  $("refsdir").value = proposed;
  $("setup-note").textContent = exists
    ? "This folder already exists and will be used as it is."
    : "This folder does not exist yet. Go will create it.";
  // Someone who opens once without the network usually means it, so the
  // choice survives the reload. Absent any answer, fetch: that is the point.
  $("auto").checked = localStorage.getItem("sextant.autoBuild") !== "0";
  $("setup").hidden = false;
}

async function goFromSetup() {
  const wanted = $("refsdir").value.trim() || null;
  localStorage.setItem("sextant.autoBuild", $("auto").checked ? "1" : "0");
  $("setup").hidden = true;
  if (!(await settleLibrary(wanted))) return;
  await openManuscript();
}

/** Agree on the library folder before anything is read or written.
 *  The setup step showed the reader this path, so Go is the confirmation and
 *  we do not ask a second time. */
async function settleLibrary(requested) {
  try {
    const answer = await postJSON("/api/workspace/library",
                                  { path: state.path, refs_dir: requested });
    if (answer.needs_confirmation) {
      await postJSON("/api/workspace/library",
                     { path: state.path, refs_dir: answer.refs_dir, create: true });
    }
    return true;
  } catch (err) {
    showReaderError(err.message);
    return false;
  }
}

//: The empty state, kept so Home can put it back. Rendering a manuscript
//: replaces the whole reader, and rebuilding this from strings would let the
//: two copies drift.
const EMPTY_READER = document.getElementById("reader").innerHTML;

/** Return to the starting state: no manuscript, no panel, no split. */
function goHome() {
  clearInterval(state.assessTimer);
  clearTimeout(state.assessRetry);
  state.path = null;
  state.ws = null;
  state.selected = null;
  state.scores = {};
  state.markerScores = {};

  closeCited();
  document.body.classList.remove("has-manuscript");
  $("reader").innerHTML = EMPTY_READER;
  $("reader-bar").hidden = true;
  $("reassess").hidden = true;
  $("effort").hidden = true;
  $("assess-all").hidden = true;
  for (const which of ["manuscript", "cited"]) {
    toggleFind(which, false);
    finds[which] = { hits: [], at: -1, query: "" };
    setFindCount(which);
  }
  $("find-manuscript").value = "";
  $("find-cited").value = "";
  setManuscriptName("");
  $("counts").textContent = "";
  $("assessing").hidden = true;
  $("refs").innerHTML = "";
  $("refs-empty").hidden = false;
  $("refs-actions").hidden = true;
  for (const stale of document.querySelectorAll(".folder, .convert-note")) {
    stale.remove();
  }
  $("tab-marker").innerHTML =
    '<p class="hint">Select a citation in the manuscript.</p>';
  $("chat-out").innerHTML = "";
  switchTab("refs");
  say("");
}

function showReaderError(message) {
  // Nothing is open, so drop back to the full-window drop zone.
  document.body.classList.remove("has-manuscript");
  closeCited();
  const reader = $("reader");
  reader.innerHTML = "";
  const box = el("div", "dropzone");
  box.appendChild(el("p", "err", message));
  box.appendChild(el("p", "hint", "Choose a different PDF above."));
  reader.appendChild(box);
}

async function openManuscript(_event, { autoBuild = true } = {}) {
  if (!state.path) return;

  busy("Reading citations…", "checking each reference against the library");
  say("reading citations…");
  try {
    state.ws = await postJSON("/api/workspace", { path: state.path });
  } catch (err) {
    idle();
    say("");
    showReaderError(err.message);
    return;
  }
  idle();
  say("");
  document.body.classList.add("has-manuscript");

  renderCounts();
  renderReader();
  renderReferences();
  renderChatTargets();
  renderBackend();

  // Build the library the first time this manuscript is opened. Only
  // references never attempted are requested, so a folder that already has
  // its papers -- or one whose remaining papers cannot be fetched -- causes
  // no network traffic at all on reopen.
  const todo = state.ws.unattempted || [];
  if (autoBuild && todo.length && $("auto").checked) {
    await buildLibrary(todo);
  }

  // Nothing is judged until asked for. Starting on open spent the whole
  // manuscript's budget before the reader could see the effort setting, let
  // alone change it -- and a judgement cannot be called back once running.
  paintAssessAll();

  // Last, so everything it points at is on screen and nothing covers it.
  maybeStartTour();
}

//: Rough prompt size per citation, measured on a 36,000-character paper --
//: the median in a real library. Enough to tell 30,000 tokens from 300,000,
//: which is the decision being made; not a billing estimate.
const TOKENS_PER_CITATION = { low: 1100, mid: 3700, high: 9700 };

/** What "assess everything" would cost, on this manuscript, right now. */
function assessableCount() {
  if (!state.ws) return 0;
  const have = new Set(state.ws.references.filter((r) => r.available).map((r) => r.key));
  const judged = state.markerScores || {};
  return state.ws.markers.filter(
    (m) => have.has(m.key) && !(String(m.id) in judged)).length;
}

function paintAssessAll() {
  const button = $("assess-all");
  const n = assessableCount();
  // Shown when there is something to assess, and pressable whenever shown.
  // It was disabled while a run was in flight, which was pointless -- the
  // server already ignores a second start -- and it left the button dead
  // whenever the flag was not cleared.
  const reachable = state.backend !== false;
  button.hidden = n === 0 || !reachable;
  button.disabled = false;
  if (button.hidden) return;
  const each = TOKENS_PER_CITATION[effort()] || TOKENS_PER_CITATION.mid;
  const total = n * each;
  const cost = total >= 1000 ? `${Math.round(total / 1000)}k` : String(total);
  button.textContent = `Assess ${n} citation${n > 1 ? "s" : ""}`;
  button.title =
    `Judge ${n} citation${n > 1 ? "s" : ""} at ${effort()} effort -- roughly `
    + `${cost} tokens in total. Change the effort first if that is not what `
    + `you want; a run cannot be called back once it starts.`;
}

/** Assess relevance for the whole manuscript in the background.
 *  Each judgement is a model call of roughly twenty seconds; doing them up
 *  front means the reader almost never waits for one. */
async function startAssessing() {
  try {
    const begun = await postJSON("/api/assess/all", { path: state.path, effort: effort() });
    // Always read the scores, even when no pass starts. A manuscript opened a
    // second time has every citation judged already, so "total" is zero --
    // and returning here left the library with no scores at all, which is
    // exactly the case where they were all available.
    await refreshScores();
    if (begun.total) watchAssessing();
  } catch {
    say("could not start the assessment");
  }
}

/** Discard every judgement for this manuscript and assess it again.
 *  Retrieval and the prompt both change; a reader who has just fixed a
 *  sentence wants it looked at afresh rather than shown a stale verdict. */
async function reassessAll() {
  if (!state.path) return;
  const button = $("reassess");
  if (button) button.disabled = true;
  try {
    state.scores = {};
    state.markerScores = {};
    await postJSON("/api/assess/reset", { path: state.path });
    await refreshScores();
    // Cleared, not restarted. The Assess button now offers the full count
    // again, with what it will cost, and waits to be pressed.
    paintAssessAll();
    say("judgements discarded");
  } catch {
    setStatus("could not start a new assessment");
  } finally {
    if (button) button.disabled = false;
  }
}

/** Pull the scores and put them in the library. */
async function refreshScores() {
  const summary = await get(
    `/api/assess/summary?path=${encodeURIComponent(state.path)}`);
  state.scores = summary.scores || {};
  state.markerScores = summary.by_marker || {};
  paintAssessAll();
  if (state.ws) {
    renderReferences();
    recolourMarkers();
  }
  return summary;
}

function watchAssessing() {
  clearInterval(state.assessTimer);
  state.assessTimer = setInterval(async () => {
    let p;
    try {
      // Scores appear in the library as they land, not only at the end.
      p = await refreshScores();
    } catch {
      clearInterval(state.assessTimer);
      return;
    }
    const el = $("assessing");
    if (p.running) {
      el.hidden = false;
      el.textContent = `assessing ${p.done}/${p.total}`;
    } else {
      clearInterval(state.assessTimer);
      el.textContent = p.total ? `${p.total} assessed` : "";
      setTimeout(() => { el.hidden = true; }, 4000);
    }
  }, 1500);
}

async function buildLibrary(keys) {
  busy(`Building the library…`,
       `${keys.length} reference${keys.length > 1 ? "s" : ""} to look up`);
  say(`building library: ${keys.length} reference${keys.length > 1 ? "s" : ""}…`);
  $("refs-actions").hidden = true;
  try {
    const result = await postJSON("/api/workspace/fetch", { path: state.path, keys });
    const failed = result.results.filter((r) => !r.available);
    // Re-open to re-verify every marker against the newly available sources.
    await openManuscript(null, { autoBuild: false });
    say(`library ready — ${result.resolved} obtained, ${failed.length} unavailable`);
    if (failed.length) showFetchFailures(failed);
  } catch (err) {
    say("");
    $("status").textContent = `library build failed: ${err.message}`;
  } finally {
    idle();
  }
}

function renderCounts() {
  const order = ["not-found", "verified", "no-source", "no-claim"];
  const counts = state.ws.counts;
  $("counts").textContent = order
    .filter((k) => counts[k])
    .map((k) => `${counts[k]} ${
      counts[k] === 1 ? label_for(k) : STATUS_LABEL_PLURAL[k] || label_for(k)}`)
    .join(" · ");
}

function renderBackend() {
  const b = state.ws.backends || {};
  $("backend").textContent = b.cli
    ? "via Claude Code"
    : b.api ? "via API key" : "no backend — prompt only";
}

/* ---------------------------------------------------------------- search */

/** Find-in-document for the two reading panes.
 *
 *  Search hits are kept apart from evidence highlights, in their own overlay
 *  and their own colour. A search must never overwrite the passage a citation
 *  is pointing at -- that highlight is the answer the reader came for. */
const finds = {
  manuscript: { hits: [], at: -1, query: "" },
  cited: { hits: [], at: -1, query: "" },
};

function findContainer(which) {
  return which === "cited" ? $("cited-body") : $("reader");
}

const findParts = (which) => which === "cited"
  ? { row: "find-cited-row", lens: "find-cited-toggle", box: "find-cited" }
  : { row: "find-manuscript-row", lens: "find-manuscript-toggle",
      box: "find-manuscript" };

/** Show or put away one pane's search.
 *
 *  Closing clears the query rather than merely hiding the box: highlights
 *  standing on the page with nothing on screen to explain them are worse than
 *  no highlights, and there would be no way to step through them either.
 */
function toggleFind(which, show) {
  const part = findParts(which);
  const row = $(part.row);
  const open = show === undefined ? row.hidden : show;
  if (open === !row.hidden) return;

  row.hidden = !open;
  $(part.lens).classList.toggle("on", open);
  $(part.lens).setAttribute("aria-expanded", String(open));

  if (open) {
    $(part.box).focus();
    $(part.box).select();
    return;
  }
  $(part.box).value = "";
  runFind(which);
}

async function runFind(which) {
  const box = $(which === "cited" ? "find-cited" : "find-manuscript");
  const query = box.value.trim();
  const state_ = finds[which];

  if (!query) {
    state_.hits = [];
    state_.at = -1;
    state_.query = "";
    paintFinds(which);
    setFindCount(which);
    return;
  }
  if (query === state_.query) return stepFind(which, 1);

  const url = which === "cited"
    ? `/api/papers/${cited.paperId}/find?q=${encodeURIComponent(query)}`
    : `/api/workspace/find?path=${encodeURIComponent(state.path)}` +
      `&q=${encodeURIComponent(query)}`;
  try {
    const found = await get(url);
    state_.hits = found.hits || [];
    state_.total = found.total || 0;
    state_.query = query;
    state_.at = state_.hits.length ? 0 : -1;
  } catch {
    state_.hits = [];
    state_.at = -1;
  }
  paintFinds(which);
  setFindCount(which);
  if (state_.at >= 0) goToFind(which);
}

function stepFind(which, delta) {
  const state_ = finds[which];
  if (!state_.hits.length) return;
  state_.at = (state_.at + delta + state_.hits.length) % state_.hits.length;
  paintFinds(which);
  setFindCount(which);
  goToFind(which);
}

function setFindCount(which) {
  const state_ = finds[which];
  const node = $(which === "cited" ? "find-cited-count" : "find-manuscript-count");
  if (!state_.query) { node.textContent = ""; return; }
  node.textContent = state_.hits.length
    ? `${state_.at + 1}/${state_.total}`
    : "none";
}

/** Paint every hit, filling the one the reader is standing on. */
function paintFinds(which) {
  const root = findContainer(which);
  for (const old of root.querySelectorAll(".find-hit")) old.remove();

  finds[which].hits.forEach((hit, index) => {
    const wrap = root.querySelector(`.page-wrap[data-page="${hit.page}"]`);
    if (!wrap) return;
    for (const b of hit.boxes) {
      const mark = el("div", index === finds[which].at ? "find-hit current" : "find-hit");
      mark.style.left = `${b.left * 100}%`;
      mark.style.top = `${b.top * 100}%`;
      mark.style.width = `${b.width * 100}%`;
      mark.style.height = `${b.height * 100}%`;
      wrap.appendChild(mark);
    }
  });
}

function goToFind(which) {
  const state_ = finds[which];
  const hit = state_.hits[state_.at];
  if (!hit) return;
  const root = findContainer(which);
  const wrap = root.querySelector(`.page-wrap[data-page="${hit.page}"]`);
  if (!wrap) return;
  if (which === "cited") { cited.page = hit.page; updateCitedCounter(); }
  wrap.scrollIntoView({ block: "start", behavior: "smooth" });
}

/** Re-run the current search when a pane's pages are rebuilt. */
function repaintFinds(which) {
  if (finds[which].query) paintFinds(which);
}

/* ---------------------------------------------------------------- reader */

function renderReader() {
  const reader = $("reader");
  reader.innerHTML = "";

  const byPage = new Map();
  for (const m of state.ws.markers) {
    if (!byPage.has(m.page)) byPage.set(m.page, []);
    byPage.get(m.page).push(m);
  }

  // Build every page up front at the right aspect ratio so the scrollbar is
  // honest, but only load the image when it comes near the viewport. Ten
  // pages at zoom 1.6 is several megabytes.
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        loadPage(entry.target);
        observer.unobserve(entry.target);
      }
    },
    { rootMargin: "800px 0px" }
  );

  for (let n = 1; n <= state.ws.pages; n++) {
    const size = state.ws.page_sizes[n - 1];
    const wrap = el("div", "page-wrap placeholder");
    wrap.dataset.page = String(n);
    wrap.style.aspectRatio = `${size.width} / ${size.height}`;

    const note = el("div", "loading-note");
    note.appendChild(el("div", "spinner"));
    note.appendChild(el("span", null, `page ${n}`));
    wrap.appendChild(note);

    for (const m of byPage.get(n) || []) {
      const box = el("div", `marker m-${m.status}`);
      box.dataset.key = m.key;
      box.style.left = `${m.box.left * 100}%`;
      box.style.top = `${m.box.top * 100}%`;
      box.style.width = `${m.box.width * 100}%`;
      box.style.height = `${m.box.height * 100}%`;
      box.title = markerTooltip(m);
      box.dataset.id = String(m.id);
      box.onclick = (e) => { e.stopPropagation(); selectMarker(m.id); };
      wrap.appendChild(box);
    }

    reader.appendChild(wrap);
    observer.observe(wrap);
  }
  $("reader-bar").hidden = false;
  $("reassess").hidden = false;
  $("effort").hidden = false;
  paintAssessAll();
  recolourMarkers();
  repaintFinds("manuscript");
}

/** What a citation marker says on hover.
 *
 *  It said the raw status -- "no-claim" -- which names the mechanism rather
 *  than the finding and reads as a verdict on the citation, which it is not.
 */
function markerTooltip(m) {
  const score = (state.scores || {})[m.key];
  const grade = score ? `${score.high}/5 · ` : "";
  return `${m.marker} ${m.key}\n${grade}${label_for(m.status)}\n\n${m.claim}`;
}

/** Once a citation is scored, the score is the better signal.
 *
 *  The status only ever said whether a figure was found, which is narrower
 *  than "is this citation any good" -- the question the colour is answering
 *  for someone scanning the page. */
function recolourMarkers() {
  const scores = state.scores || {};
  for (const box of document.querySelectorAll(".marker")) {
    const score = scores[box.dataset.key];
    for (const tier of ["good", "fair", "weak", "bad"]) {
      box.classList.remove(`s-${tier}`);
    }
    if (!score) continue;
    const tier = score.high >= 4 ? "good"
               : score.high >= 3 ? "fair"
               : score.high >= 1 ? "weak" : "bad";
    box.classList.add(`s-${tier}`);
  }
  for (const m of (state.ws && state.ws.markers) || []) {
    const box = document.querySelector(`.marker[data-id="${m.id}"]`);
    if (box) box.title = markerTooltip(m);
  }
}

function loadPage(wrap) {
  const n = wrap.dataset.page;
  const img = el("img");
  img.loading = "lazy";
  img.alt = `page ${n}`;
  img.src = `/api/workspace/page/${n}.png?zoom=1.6&path=${encodeURIComponent(state.path)}`;
  img.onload = () => {
    wrap.classList.remove("placeholder");
    wrap.querySelector(".loading-note")?.remove();
  };
  // Without this a failed render spins forever and looks like a slow network.
  img.onerror = () => {
    wrap.classList.remove("placeholder");
    wrap.classList.add("failed");
    img.remove();
    const note = wrap.querySelector(".loading-note");
    if (note) note.textContent = `page ${n} could not be rendered`;
  };
  wrap.insertBefore(img, wrap.firstChild);
}

/* ------------------------------------------------------------ references */

function renderReferences() {
  const list = $("refs");
  list.innerHTML = "";
  $("refs-empty").hidden = true;
  for (const stale of list.parentElement.querySelectorAll(".folder, .convert-note")) {
    stale.remove();
  }

  const missing = state.ws.references.filter((r) => !r.available);
  $("refs-actions").hidden = false;
  $("fetch-all").hidden = missing.length === 0;
  $("fetch-all").textContent = `Retry ${missing.length} online`;
  const where = el("div", "folder");
  const folderHead = el("div", "folder-head");
  folderHead.appendChild(el("span", "label", "References folder"));
  // The same card that chose this folder in the first place, so there is one
  // place that answers "where do the papers go" rather than two that can
  // disagree. It arrives filled in with the folder in force.
  const change = el("button", null, "Change…");
  change.type = "button";
  change.title = "Use a different folder for this manuscript's references";
  change.onclick = () => chooseManuscript(state.path, { reopening: true });
  folderHead.appendChild(change);
  where.appendChild(folderHead);
  const path = el("code", "path", state.ws.refs_dir || "");
  path.title = "Click to copy";
  path.onclick = () => {
    navigator.clipboard.writeText(state.ws.refs_dir || "").then(() => say("path copied"));
  };
  where.appendChild(path);
  list.parentElement.insertBefore(where, $("refs-actions"));

  // The action belongs where the problem is stated. Telling someone to press
  // a differently-named button elsewhere is one indirection too many.
  const stuck = state.ws.unconverted || [];
  if (stuck.length) {
    const note = el("div", "convert-note");
    const what = stuck.length === 1 ? "is not a PDF" : "are not PDFs";
    note.appendChild(el("div", null,
      `${stuck.length} document${stuck.length > 1 ? "s" : ""} ${what}`));
    note.appendChild(convertPicker(stuck));
    list.parentElement.insertBefore(note, $("refs-actions"));
  }

  $("folder-hint").textContent = missing.length
    ? `${missing.length} of ${state.ws.references.length} need a manual copy. ` +
      "Download each, drop it anywhere in the refs folder, then press Update."
    : `All ${state.ws.references.length} references are in the library.`;

  // A header row, so the columns say what they are. Every row uses the same
  // track sizes, which is what keeps them aligned down the page.
  const head = el("li", "head");
  for (const [label, hint] of [
    ["Ref", "The citation marker as printed in the manuscript"],
    ["Title", "The reference, as the library knows it"],
    ["Score", "Best judgement across this reference's citations, out of 5"],
    ["Cited", "How many times the manuscript cites it"],
    ["Pages", "Length of the paper in the library"],
  ]) {
    const cell = el("span", null, label);
    cell.title = hint;
    head.appendChild(cell);
  }
  list.appendChild(head);

  for (const r of state.ws.references) {
    // Greyed rather than hidden: a reference with no paper is still part of
    // the bibliography, and its row is where the reader goes to supply one.
    const li = el("li", r.available ? null : "missing");
    li.appendChild(el("span", "num", r.marker));

    const entry = el("div", "entry");
    const key = el("span", "key", r.key);
    key.classList.add("clickable");
    key.onclick = () => (r.available ? openReference(r) : showLookup(r));
    entry.appendChild(key);
    // The citation as the manuscript prints it: authors, title, venue, year.
    // Preferred over the parsed title, which is a guess at which segment of
    // that line is the title and is sometimes the journal name or a URL. This
    // is the text you would paste into a search, and it is never wrong.
    const said = r.raw || r.title;
    if (said) {
      const line = el("span", "title", said);
      line.title = r.raw || r.title;
      entry.appendChild(line);
    }
    if (!r.available) {
      const actions = el("div", "row-actions");
      const btn = el("button", null, "Fetch");
      btn.onclick = () => fetchKeys([r.key], btn);
      actions.appendChild(btn);
      const manual = el("span", "manual", "⬇ add manually");
      manual.title = "Find it yourself, then drop it in the references folder";
      actions.appendChild(manual);
      entry.appendChild(actions);
    }
    li.appendChild(entry);

    // Three states, not two: a score, a deliberate abstention, and no paper
    // to judge in the first place.
    const score = r.available ? (state.scores || {})[r.key] : null;
    li.appendChild(score ? scoreChip(score)
      : r.available ? noScoreChip({ chip: true })
      : el("span", "col dash", "—"));

    const cited = el("span", "col count", `${r.cited_count}`);
    cited.title = `Cited ${r.cited_count} time${r.cited_count > 1 ? "s" : ""}`;
    li.appendChild(cited);

    const pages = el("span", "col count", r.available ? `${r.pages}` : "—");
    if (r.available) pages.title = `${r.pages} pages`;
    li.appendChild(pages);

    list.appendChild(li);
  }
}

/** Take reference papers from the browser into the library.
 *  Before this the only way in was to find a content-hashed folder under
 *  ~/.local/share in a file manager, which cost a user two misplaced files. */
async function addReferenceFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;

  busy("Adding to the library…",
       files.length === 1 ? files[0].name : `${files.length} files`);
  const form = new FormData();
  form.append("path", state.path);
  for (const f of files) form.append("files", f);

  try {
    const response = await fetch("/api/workspace/add", { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);

    await openManuscript(null, { autoBuild: false });
    const parts = [];
    if (data.matched.length) {
      parts.push(`matched ${data.matched.map((m) => m.key).join(", ")}`);
    } else if (data.saved.length) {
      parts.push("added, but no reference matched — check the title");
    }
    for (const r of data.rejected || []) parts.push(`${r.name}: ${r.reason}`);
    say(parts.join(" · "));
  } catch (err) {
    say(`could not add: ${err.message}`);
  } finally {
    idle();
  }
}

/** Convert the office documents sitting in the library, then match them.
 *  Conversion on its own would leave a PDF nobody had filed, so this does the
 *  same work as Update -- it is just reachable from where the problem is. */
/** Convert, but say which. A 27 MB specification is tens of seconds, so
 *  "Convert 4 documents" made the reader pay for three they did not want in
 *  order to get the one they did. The button opens the list instead.
 */
function convertPicker(names) {
  const wrap = el("div", "convert-pick");
  const open = el("button", null, "Convert…");
  wrap.appendChild(open);

  const form = el("div", "convert-form");
  form.hidden = true;
  const boxes = names.map((name) => {
    const row = el("label", "convert-row");
    const tick = el("input");
    tick.type = "checkbox";
    tick.checked = true;
    tick.value = name;
    row.appendChild(tick);
    row.appendChild(el("span", "convert-name", name));
    form.appendChild(row);
    return tick;
  });

  const row = el("div", "row");
  const go = el("button", null, "Convert");
  const cancel = el("button", null, "Cancel");
  row.appendChild(go);
  row.appendChild(cancel);
  form.appendChild(row);
  wrap.appendChild(form);

  const chosen = () => boxes.filter((b) => b.checked).map((b) => b.value);
  const retitle = () => {
    const n = chosen().length;
    go.textContent = n === names.length && n > 1 ? "Convert all" : `Convert ${n}`;
    go.disabled = n === 0;
  };
  for (const box of boxes) box.onchange = retitle;
  retitle();

  open.onclick = () => { form.hidden = false; open.hidden = true; };
  cancel.onclick = () => { form.hidden = true; open.hidden = false; };
  go.onclick = () => convertDocuments(chosen(), go);
  return wrap;
}

async function convertDocuments(names, button) {
  if (!names.length) return;
  if (button) button.disabled = true;
  busy("Converting…",
       names.length === 1 ? names[0] : `${names.length} documents`);
  try {
    const result = await postJSON("/api/workspace/rescan",
                                  { path: state.path, convert: names });
    await openManuscript(null, { autoBuild: false });

    const done = (result.converted || []).filter((c) => c.pdf).map((c) => c.source);
    const failed = (result.converted || []).filter((c) => c.error);
    const parts = [];
    if (done.length) parts.push(`converted ${done.join(", ")}`);
    if (result.matched.length) {
      parts.push(`matched ${result.matched.map((m) => m.key).join(", ")}`);
    } else if (done.length) {
      parts.push("but no reference matched — check the title");
    }
    for (const f of failed) parts.push(`${f.source}: ${f.error}`);
    say(parts.join(" · ") || "nothing to convert");
  } catch (err) {
    say(`conversion failed: ${err.message}`);
    if (button) button.disabled = false;
  } finally {
    idle();
  }
}

async function updateFromFolder() {
  const button = $("update");
  button.disabled = true;
  say("scanning the folder (converting any documents)…");
  try {
    const result = await postJSON("/api/workspace/rescan", { path: state.path });
    await openManuscript(null, { autoBuild: false });

    const converted = (result.converted || []).filter((c) => c.pdf);
    const failed = (result.converted || []).filter((c) => c.error);
    const parts = [];
    if (converted.length) parts.push(`converted ${converted.length}`);
    parts.push(result.matched.length
      ? `matched ${result.matched.map((m) => m.key).join(", ")}`
      : "no new papers matched a reference");
    if (failed.length) parts.push(`${failed[0].source}: ${failed[0].error}`);
    say(parts.join(" · "));
  } catch (err) {
    say(`update failed: ${err.message}`);
  } finally {
    button.disabled = false;
  }
}

async function fetchKeys(keys, button) {
  if (button) { button.disabled = true; button.textContent = "…"; }
  say(`fetching ${keys.length}…`);
  try {
    const result = await postJSON("/api/workspace/fetch", { path: state.path, keys });
    const failed = result.results.filter((r) => !r.available);
    say(`${result.resolved} obtained, ${failed.length} not`);
    if (failed.length) showFetchFailures(failed);
    await openManuscript(null, { autoBuild: false });  // re-verify
  } catch (err) {
    say("");
    if (button) { button.disabled = false; button.textContent = "Fetch"; }
    alert(err.message);
  }
}

const isWebLink = (url) => /^https?:\/\//i.test(String(url).trim());

function showFetchFailures(failed) {
  switchTab("marker");
  const panel = $("tab-marker");
  panel.innerHTML = "";
  panel.appendChild(el("h3", null, `${failed.length} could not be fetched`));
  panel.appendChild(el("p", "hint",
    "Download each and add it below — the next scan will pick it up."));
  for (const r of failed) {
    const block = el("div", "field");
    block.appendChild(el("div", "label", r.key));
    block.appendChild(el("div", null, r.reason || r.status));
    // From OpenAlex and Unpaywall, so only ever a web link: a javascript:
    // URL here would run in the viewer's own page when clicked.
    const pages = (r.landing_pages || []).filter(isWebLink);
    for (const url of pages) {
      const a = el("a", null, url);
      a.href = url; a.target = "_blank"; a.rel = "noreferrer";
      block.appendChild(a);
      block.appendChild(el("br"));
    }
    panel.appendChild(block);
  }
}

/* --------------------------------------------------------------- markers */


async function selectMarker(id, { scroll = false } = {}) {
  const marker = state.ws.markers.find((m) => m.id === id);
  if (!marker) return;
  state.selected = id;

  for (const node of document.querySelectorAll(".marker.selected")) {
    node.classList.remove("selected");
  }
  const node = document.querySelector(`.marker[data-id="${id}"]`);
  if (node) {
    node.classList.add("selected");
    if (scroll) {
      node.scrollIntoView({ block: "center", behavior: "smooth" });
      node.classList.remove("flash");
      void node.offsetWidth;
      node.classList.add("flash");
    }
  }

  switchTab("marker");
  const panel = $("tab-marker");
  panel.innerHTML = "";

  // One request serves the navigation below; each rebuilds the workspace.
  const context = await markerContext(marker);
  addSiblingNav(panel, marker, context);

  // The card is the panel: a score, the reasoning, the sentence in each
  // document, and a note. Nothing else earns the space.
  const card = el("div", "card-body");
  panel.appendChild(card);
  renderMarkerCard(card, marker, null);

  if (marker.paper_id) {
    showCited(marker.paper_id, marker.key, marker.cited_page || 1,
              {}, marker.marker);
    runAssess(marker, null, card, { onlyIfReady: true });
    loadPassages(marker, card);
  }
}

/** Where to start reading, found without a model.
 *
 *  Free and offline, so it runs for every citation opened rather than waiting
 *  to be asked for. It redraws whatever the card was last drawn with, so it
 *  cannot fight with a judgement that arrives at the same time.
 */
async function loadPassages(marker, card) {
  if (state.passages[marker.id]) return;
  try {
    state.passages[marker.id] = await postJSON("/api/marker/passages", {
      path: state.path, marker_id: marker.id,
    });
  } catch {
    return;
  }
  if (state.selected === marker.id && card.drawnWith) {
    renderMarkerCard(card, ...card.drawnWith.slice(0).map((v, i) => i === 0 ? marker : v));
  }
}

async function runAssess(marker, button, out, { onlyIfReady = false } = {}) {
  let r;
  try {
    r = await postJSON("/api/assess", {
      path: state.path, marker_id: marker.id, only_ready: onlyIfReady,
      effort: effort(),
    });
  } catch {
    return;                       // the card already stands without a verdict
  }

  if (onlyIfReady && r.pending) {
    let progress = null;
    try {
      progress = await get(
        `/api/assess/progress?path=${encodeURIComponent(state.path)}`);
    } catch { /* no queue information; leave the card as it is */ }
    if (progress && progress.running) {
      renderMarkerCard(out, marker, null, {
        waiting: `assessing — queued, ${progress.done}/${progress.total} done`,
      });
      clearTimeout(state.assessRetry);
      state.assessRetry = setTimeout(() => {
        if (state.selected === marker.id) {
          runAssess(marker, button, out, { onlyIfReady: true });
        }
      }, 4000);
    } else {
      renderMarkerCard(out, marker, null, { offer: true });
    }
    return;
  }
  renderMarkerCard(out, marker, r);
}

/** The whole panel for one citation, in one place.
 *
 *  Score, assessment, the sentence in the manuscript, the passages in the
 *  cited paper, and a note. Each text links to where it lives. Anything that
 *  was not one of those five -- the quantity checked, every occurrence of it,
 *  the passages searched, a footnote saying when the judgement was made --
 *  was competing with them for attention.
 */
function renderMarkerCard(card, marker, r, { waiting = "", offer = false } = {}) {
  // Stashed so the free passage lookup can redraw the same card when it
  // lands, without knowing how it was drawn.
  card.drawnWith = [marker, r, { waiting, offer }];
  card.innerHTML = "";
  const quotes = (r && r.quotes) || [];

  /* 1 — score */
  const head = el("div", "verdict-head");
  if (r && typeof r.score === "number") head.appendChild(scoreBadge(r.score));
  else if (r) head.appendChild(noScoreChip());
  if (r && r.revised) {
    const tag = el("span", "badge b-no-claim", "revised");
    tag.title = "Judged again with your note";
    head.appendChild(tag);
  }
  head.appendChild(el("code", null, `${marker.marker} ${marker.key}`));
  card.appendChild(head);

  /* 2 — assessment */
  // Nothing has judged this one and nothing is going to unless asked. Without
  // this the only way to judge a single citation was to judge every citation.
  if (offer) {
    const ask = el("div", "offer");
    if (state.backend === false) {
      // No button, but the rest of the card still stands: the sentence, the
      // passages and the mechanical finding are all worth reading without a
      // model, and they are what this page is for.
      ask.appendChild(el("p", "hint",
        "Not judged. Judging needs Claude Code on your PATH, or "
        + "ANTHROPIC_API_KEY. Everything else here works without it."));
      card.appendChild(ask);
    } else {
    const go = el("button", null, "Judge this citation");
    go.title = `One model call at ${effort()} effort. The Assess button in the `
             + "bar does the whole manuscript.";
    go.onclick = () => {
      go.disabled = true;
      card.innerHTML = "";
      card.appendChild(spinner("judging this citation…", true));
      runAssess(marker, null, card);
    };
    ask.appendChild(el("p", "hint", "Not judged yet."));
    ask.appendChild(go);
    card.appendChild(ask);
    }
  }
  if (waiting) {
    card.appendChild(spinner(waiting, true));
  } else if (r && r.why) {
    card.appendChild(labelled("Assessment", r.why));
  }

  /* 3 — the sentence in the manuscript */
  const mine = el("div", "field");
  mine.appendChild(el("div", "label", `Manuscript · p. ${marker.page}`));
  const claim = el("div", "quote passage clickable", marker.claim || "(no text)");
  claim.title = "Go to this citation in the manuscript";
  claim.onclick = () => selectMarker(marker.id, { scroll: true });
  mine.appendChild(claim);
  card.appendChild(mine);

  /* 4 — the passages in the cited paper, one entry each */
  const highlights = {};
  for (const q of quotes) {
    if (q.boxes && q.boxes.length) highlights[q.page] = q.boxes;
  }
  const theirs = el("div", "field");
  theirs.appendChild(el("div", "label", `${marker.key} · cited paper`));

  if (quotes.length) {
    for (const q of quotes) {
      const row = el("div", "quote passage clickable", `p. ${q.page} — ${q.text}`);
      row.title = "Go to this passage in the cited paper";
      row.onclick = () => {
        showCited(marker.paper_id, marker.key, q.page, highlights,
                  `${marker.marker} · quoted`);
        goToCitedPage(q.page);
      };
      theirs.appendChild(row);
    }
    if (Object.keys(highlights).length) {
      showCited(marker.paper_id, marker.key,
                r.page || Number(Object.keys(highlights)[0]),
                highlights, `${marker.marker} · quoted`);
    }
  } else if (marker.excerpt) {
    const row = el("div", "quote passage clickable",
                   `p. ${marker.cited_page} — ${marker.excerpt}`);
    row.title = "Go to this passage in the cited paper";
    row.onclick = () => openMarkerEvidence(marker);
    theirs.appendChild(row);
  } else if (!marker.paper_id) {
    theirs.appendChild(el("p", "hint", "Not in the library."));
  } else if (!r && ((state.passages[marker.id] || {}).passages || []).length) {
    // Found by term overlap, at no cost and with no model. A place to look,
    // never a verdict: measured on a real manuscript, a claim scores against
    // its own cited paper the same as against a random other paper from the
    // same library, so the ranking cannot tell a real citation from a
    // plausible substitute. Each one is drawn only where recover_span located
    // it in the page layout.
    const found = state.passages[marker.id];
    for (const passage of found.passages) {
      const row = el("div", "quote passage clickable maybe",
                     `p. ${passage.page} — ${passage.text}`);
      row.title = "Keyword match. Go to it in the cited paper.";
      row.onclick = () => {
        const boxes = passage.boxes && passage.boxes.length
          ? { [passage.page]: passage.boxes } : {};
        showCited(marker.paper_id, marker.key, passage.page, boxes,
                  `${marker.marker} · closest passages`);
        goToCitedPage(passage.page);
      };
      theirs.appendChild(row);
    }
    theirs.appendChild(el("p", "hint",
      "Closest passages by keyword, not a judgement. Nothing has read them."));
  } else if (r) {
    // Something looked. This is a finding.
    theirs.appendChild(el("p", "hint", "No passage carries this sentence."));
  } else if (!waiting) {
    // Nothing has looked. Saying "no passage carries this sentence" here
    // reported the result of a check that never ran -- and once judging
    // became opt-in, that was every citation on opening a manuscript.
    theirs.appendChild(el("p", "hint",
      marker.status === "not-found"
        ? "The figure is not in the cited paper. Nothing has looked for the "
          + "sentence itself yet."
        : "Not looked at yet."));
  }
  card.appendChild(theirs);

  /* 5 — note */
  card.appendChild(labelled("Note", noteFor(marker, r)));

  if (r) addRevision(card, marker, r);
}

/** What the mechanical check did, in a sentence.
 *
 *  This used to be a one-word badge. "no-claim" and "verified" name the
 *  mechanism rather than the finding, and a reader has to have been told what
 *  they mean; said in full they need no glossary, and there is room here
 *  because the score already carries the verdict.
 */
function noteFor(marker, assessment) {
  const figure = marker.quantity
    ? `${marker.quantity.value} ${marker.quantity.unit}`
    : null;

  let note;
  switch (marker.status) {
    case "verified":
      note = `This sentence names ${figure}, and that figure was found in the `
           + `cited paper${marker.cited_page ? ` on page ${marker.cited_page}` : ""}. `
           + "Finding the number is not the same as the paper supporting the "
           + "sentence, which is what the assessment above weighs.";
      break;
    case "not-found":
      note = `This sentence names ${figure}, and that figure appears nowhere `
           + "in the cited paper. Either the paper gives it differently, or it "
           + "is not the source for this number.";
      break;
    case "no-source":
      note = "The cited paper is not in the library, so nothing here has been "
           + "checked against it. Add it and this citation will be assessed.";
      break;
    default:
      note = "This sentence names no figure, so there was nothing to check "
           + "mechanically. The assessment above is the whole answer.";
  }

  // Say why the score is missing. Withholding it is deliberate -- Claude is
  // told to abstain when the passages look like the wrong pages -- but an
  // empty space said nothing, and the question came back every time.
  if (assessment && typeof assessment.score !== "number") {
    note += " It is marked N, not valued: the passages retrieved look like the "
          + "wrong pages, so a score would fault the citation for a retrieval "
          + "miss rather than judge it. Press Re-assess to try again.";
  }

  // The workspace sometimes has more to say -- a joint citation, a file with
  // no text layer. Only when it adds something: the common reasons restate
  // the sentence above word for word.
  const restates = [
    "no quantity to check",
    "no local PDF",
    "appears nowhere in the cited paper",
  ].some((dull) => (marker.reason || "").includes(dull));
  if (marker.reason && !restates) note += ` (${marker.reason})`;
  return note;
}

/** Argue for a citation and have it judged again.
 *
 *  The reader knows their field and their intent, and the model saw four
 *  retrieved passages. When those disagree the reader should be able to say
 *  why, and get a fresh judgement rather than a fixed one. */
function addRevision(card, marker, r) {
  if (r.note) {
    const said = labelled("Your note", r.note, "quote");
    said.classList.add("revision-note");
    card.appendChild(said);
  }

  const wrap = el("div", "revision");
  const open = el("button", null, r.revised ? "Revise again" : "Revise assessment");
  wrap.appendChild(open);

  // An argument is worth making and worth taking back. Without this the only
  // way out was Re-assess, which discards every judgement in the manuscript
  // to undo one. The judgement it puts back is the one that was displaced,
  // not a fresh call that might land somewhere else again.
  if (r.revised) {
    const back = el("button", null, "Revert");
    back.title = "Discard your note and put back the judgement it replaced";
    back.onclick = async () => {
      back.disabled = true;
      card.innerHTML = "";
      card.appendChild(spinner("putting the earlier judgement back…", true));
      try {
        const restored = await postJSON("/api/assess/revert", {
          path: state.path, marker_id: marker.id,
        });
        renderMarkerCard(card, marker, restored);
      } catch (err) {
        renderMarkerCard(card, marker, r);
        card.appendChild(el("p", "err", err.message));
      }
      state.scores = {};            // the reference's score has moved back
      refreshScores().catch(() => {});
    };
    wrap.appendChild(back);
  }

  const form = el("div", "revision-form");
  form.hidden = true;
  const box = el("textarea");
  box.rows = 3;
  box.placeholder = "Why does this reference belong here?";
  const send = el("button", null, "Re-assess");
  const cancel = el("button", null, "Cancel");
  form.appendChild(box);
  const row = el("div", "row");
  row.appendChild(send);
  row.appendChild(cancel);
  form.appendChild(row);
  wrap.appendChild(form);

  open.onclick = () => { form.hidden = false; open.hidden = true; box.focus(); };
  cancel.onclick = () => { form.hidden = true; open.hidden = false; };
  send.onclick = async () => {
    const note = box.value.trim();
    if (!note) return;
    send.disabled = true;
    card.innerHTML = "";
    card.appendChild(spinner("re-assessing with your note…", true));
    try {
      const revised = await postJSON("/api/assess", {
        path: state.path, marker_id: marker.id, note, effort: effort(),
      });
      renderMarkerCard(card, marker, revised);
      state.scores = {};            // the reference's score may have moved
      refreshScores().catch(() => {});
    } catch (err) {
      renderMarkerCard(card, marker, r);
      card.appendChild(el("p", "err", err.message));
    }
  };
  card.appendChild(wrap);
}

/** Open the cited paper at a verified quantity, re-locating it first so the
 *  highlight is one we just confirmed. */
async function openMarkerEvidence(marker) {
  const hit = await get(
    `/api/papers/${marker.paper_id}/locate?q=${encodeURIComponent(
      marker.excerpt.slice(0, 120))}`);
  showCited(marker.paper_id, marker.key, hit.found ? hit.page : 1,
            hit.found ? { [hit.page]: hit.boxes } : {},
            `${marker.marker} · cited quantity`);
  if (hit.found) goToCitedPage(hit.page);
}

/** A reference's score in the library list: the best of its citations.
 *  A work can be cited well in one place and loosely in another; the list
 *  answers "is this reference pulling its weight anywhere", and the panel
 *  answers it per citation. */
function scoreChip({ low, high, n, revised }) {
  const tier = high >= 4 ? "good" : high >= 3 ? "fair" : high >= 1 ? "weak" : "bad";
  // A score reached after the reader argued for the citation is not the same
  // claim as one reached without, and the list showed the two identically.
  const chip = el("span", `score chip score-${tier}${revised ? " argued" : ""}`);
  chip.appendChild(el("strong", null, String(high)));
  chip.appendChild(el("span", "outof", "/5"));
  chip.title = (n === 1
    ? `Scored ${high} of 5`
    : `Best of ${n} citations: ${high} of 5 (lowest ${low})`)
    + (revised ? " — after your note. Open the citation to revert it." : "");
  return chip;
}

/** 0 means remove the citation, 5 means it is doing its job. */
function scoreBadge(score) {
  const tier = score >= 4 ? "good" : score >= 3 ? "fair" : score >= 1 ? "weak" : "bad";
  const wrap = el("span", `score score-${tier}`);
  wrap.appendChild(el("strong", null, String(score)));
  wrap.appendChild(el("span", "outof", "/5"));
  wrap.title = {
    good: "The cited paper states this",
    fair: "Supports the general point; specifics not evidenced",
    weak: "On topic only — a better source would help",
    bad: "Unrelated — remove or replace",
  }[tier];
  return wrap;
}

/** No score, said out loud.
 *
 *  Claude is told to write SCORE: -1 when the excerpts look like the wrong
 *  pages rather than the wrong paper, because scoring then would fault the
 *  citation for a retrieval miss. That was rendered as nothing at all, so a
 *  deliberate abstention looked identical to an assessment that had not run,
 *  and the only way to tell was to read the paragraph. */
function noScoreChip({ chip = false } = {}) {
  const wrap = el("span", `score score-nv${chip ? " chip" : ""}`);
  wrap.appendChild(el("strong", null, "N"));
  const declined =
    "the passages found look like the wrong pages, so scoring would fault the "
    + "citation for a retrieval miss rather than judge it.";
  // In a list, N stands for every reference without a score -- before any
  // judgement, all of them -- so it cannot claim Claude declined to score.
  wrap.title = chip
    ? `N — no score yet: not judged, or judged without one because ${declined}`
    : `N — not valued: ${declined}`;
  return wrap;
}

async function markerContext(marker) {
  try {
    return await postJSON("/api/marker/occurrences",
                          { path: state.path, marker_id: marker.id });
  } catch {
    return null;
  }
}

/** Move between the citations of one reference without going back to the list. */
function addSiblingNav(panel, marker, data) {
  const reference = state.ws.references.find((r) => r.key === marker.key);
  const siblings = (data && data.siblings) || [];

  const bar = el("div", "siblings");

  // Always offer the way back, even for a work cited once: a reader who has
  // gone marker -> cited paper needs a route to the reference and its other
  // citations without hunting the list again.
  const back = el("button", "back", `‹ ${marker.key}`);
  back.title = siblings.length > 1
    ? `All ${siblings.length} citations of this reference`
    : "Back to this reference";
  back.onclick = () =>
    reference && (reference.available ? openReference(reference) : showLookup(reference));
  bar.appendChild(back);

  if (siblings.length > 1) {
    bar.appendChild(el("span", "count",
      `citation ${data.position + 1} of ${siblings.length}`));
    // Chevrons alone: the count beside them already says what they step
    // through, and the two labels cost the width that broke this row.
    const prev = el("button", "step", "‹");
    const next = el("button", "step", "›");
    // A chevron has no accessible name of its own; title is a tooltip, not a
    // label, and a screen reader announces the button as "button".
    for (const [button, what] of [[prev, "Previous"], [next, "Next"]]) {
      button.title = `${what} citation of this reference`;
      button.setAttribute("aria-label", button.title);
    }
    prev.disabled = data.position === 0;
    next.disabled = data.position === siblings.length - 1;
    prev.onclick = () => selectMarker(siblings[data.position - 1].id, { scroll: true });
    next.onclick = () => selectMarker(siblings[data.position + 1].id, { scroll: true });
    bar.appendChild(prev);
    bar.appendChild(next);
  } else {
    bar.appendChild(el("span", "count", "cited once"));
  }
  panel.appendChild(bar);
}

function labelled(label, text, cls) {
  const wrap = el("div", "field");
  wrap.appendChild(el("div", "label", label));
  wrap.appendChild(el("div", cls || null, text));
  return wrap;
}


/** Everything needed to find a paper that no resolver could reach.
 *  Pressing it used to do nothing at all, which is the least helpful possible
 *  response to the references that need the most work. */
function showLookup(reference) {
  switchTab("marker");
  const panel = $("tab-marker");
  panel.innerHTML = "";

  const head = el("div", "field");
  head.appendChild(el("span", "badge b-no-source", "not in the library"));
  head.appendChild(document.createTextNode(" "));
  head.appendChild(el("code", null, `${reference.marker} ${reference.key}`));
  panel.appendChild(head);

  if (reference.title) panel.appendChild(labelled("Title", reference.title));
  if (reference.doi) panel.appendChild(labelled("DOI", reference.doi));
  if (reference.raw) {
    panel.appendChild(labelled("As printed in your bibliography",
                               reference.raw, "quote"));
  }

  const query = encodeURIComponent(reference.title || reference.key);
  const links = [
    ["Google Scholar", `https://scholar.google.com/scholar?q=${query}`],
    ["OpenAlex", `https://openalex.org/works?search=${query}`],
    ["Crossref", `https://search.crossref.org/?q=${query}`],
  ];
  if (reference.doi) {
    links.unshift(["doi.org", `https://doi.org/${reference.doi}`]);
  }

  const search = el("div", "field");
  search.appendChild(el("div", "label", "Find it"));
  for (const [name, url] of links) {
    const a = el("a", "lookup", name);
    a.href = url;
    a.target = "_blank";
    a.rel = "noreferrer";
    search.appendChild(a);
  }
  panel.appendChild(search);

  // Matching by title is a convenience and it will sometimes be wrong. When
  // the reader already knows which paper this is, let them just say so.
  const pick = el("label", "filebtn small");
  pick.textContent = `Choose the PDF for ${reference.key}`;
  const input = el("input");
  input.type = "file";
  input.accept = ".pdf,.doc,.docx,.rtf,.odt";
  input.hidden = true;
  input.onchange = () => {
    assignReferenceFile(reference, input.files[0]);
    input.value = "";
  };
  pick.appendChild(input);
  panel.appendChild(pick);

  panel.appendChild(el("p", "hint",
    "Files it under this reference directly, without title matching."));

  const sites = state.ws.markers.filter((m) => m.key === reference.key);
  panel.appendChild(el("div", "label",
    `Cited ${sites.length} time${sites.length > 1 ? "s" : ""} in your manuscript`));
  const list = el("ul", "sites");
  for (const m of sites) {
    const li = el("li");
    li.appendChild(el("span", "where", `p. ${m.page}`));
    li.appendChild(el("span", "snippet", m.claim || "(no surrounding text)"));
    li.onclick = () => selectMarker(m.id, { scroll: true });
    list.appendChild(li);
  }
  panel.appendChild(list);
}

/** File a chosen document under a chosen reference, no matching involved. */
async function assignReferenceFile(reference, file) {
  if (!file) return;
  busy(`Filing under ${reference.key}…`, file.name);
  const form = new FormData();
  form.append("path", state.path);
  form.append("key", reference.key);
  form.append("file", file);
  try {
    const response = await fetch("/api/workspace/assign",
                                 { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    await openManuscript(null, { autoBuild: false });
    say(`${data.key} filed — ${data.pages} pages`);
    const updated = state.ws.references.find((r) => r.key === data.key);
    if (updated && updated.available) openReference(updated);
  } catch (err) {
    say(`could not file it: ${err.message}`);
  } finally {
    idle();
  }
}

function openReference(reference) {
  switchTab("marker");
  const panel = $("tab-marker");
  panel.innerHTML = "";

  const head = el("div", "field");
  head.appendChild(el("code", null, `${reference.marker} ${reference.key}`));
  panel.appendChild(head);
  if (reference.title) panel.appendChild(labelled("Title", reference.title));

  const sites = state.ws.markers.filter((m) => m.key === reference.key);
  panel.appendChild(el("div", "label",
    `Cited ${sites.length} time${sites.length > 1 ? "s" : ""} in your manuscript`));

  const list = el("ul", "sites");
  for (const m of sites) {
    const li = el("li");
    li.appendChild(el("span", "where", `p. ${m.page}`));
    li.appendChild(el("span", "snippet", m.claim || "(no surrounding text)"));
    const score = (state.markerScores || {})[String(m.id)];
    li.appendChild(typeof score === "number"
      ? scoreChip({ low: score, high: score, n: 1 })
      : noScoreChip({ chip: true }));
    li.onclick = () => selectMarker(m.id, { scroll: true });
    list.appendChild(li);
  }
  panel.appendChild(list);

  if (reference.paper_id) {
    // "cited 1x" tells a reader nothing they did not just do, and the shorthand
    // reads as jargon in a pane that otherwise speaks in words. The count earns
    // its place only where it is a fact you did not have.
    showCited(reference.paper_id, reference.key, 1, {},
              sites.length > 1 ? `cited ${sites.length} times` : "");
  }
}

/* ------------------------------------------------- cited-paper pane */

const cited = { paperId: null, page: 1, pages: 1, highlights: {},
                ratio: '1 / 1.4142', observer: null };

/** `highlights` maps a page number to its boxes, so every aligned passage
 *  can be painted at once rather than only the one we happened to open at. */
async function showCited(paperId, key, page, highlights, subtitle) {
  $("cited").hidden = false;
  $("splitter").hidden = false;
  document.body.classList.add("cited-open");
  // Re-apply now that both panes have a measurable width.
  setSplit(storedSplit());
  $("cited-title").textContent = key;
  $("cited-sub").textContent = subtitle || "";
  const body = $("cited-body");
  body.innerHTML = "";
  body.appendChild(spinner("opening the cited paper…"));

  let detail;
  try {
    detail = await get(`/api/papers/${paperId}`);
  } catch (err) {
    body.innerHTML = "";
    body.appendChild(el("p", "err", `could not open it: ${err.message}`));
    return;
  }

  if (cited.paperId !== paperId) {
    finds.cited = { hits: [], at: -1, query: "" };
    $("find-cited").value = "";
    setFindCount("cited");
  }
  cited.paperId = paperId;
  cited.pages = detail.pages;
  cited.ratio = `${detail.width} / ${detail.height}`;
  cited.page = Math.min(Math.max(1, page || 1), detail.pages);
  cited.highlights = highlights || {};

  $("cited-title").textContent =
    detail.title && detail.title !== "(untitled)" ? detail.title : key;
  renderCited();
  goToCitedPage(cited.page, "auto");
}

/** Every page stacked and lazily loaded, the same as the manuscript.
 *  One page at a time with arrow buttons meant the pane could not be
 *  scrolled through at all, which is the only way anyone reads a paper. */
function renderCited() {
  const body = $("cited-body");
  body.innerHTML = "";

  if (cited.observer) cited.observer.disconnect();
  cited.observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        loadCitedPage(entry.target);
        cited.observer.unobserve(entry.target);
      }
    },
    { root: body, rootMargin: "1200px 0px" }
  );

  for (let n = 1; n <= cited.pages; n++) {
    const wrap = el("div", "page-wrap placeholder");
    wrap.dataset.page = String(n);
    wrap.style.aspectRatio = cited.ratio;

    const note = el("div", "loading-note");
    note.appendChild(el("div", "spinner"));
    note.appendChild(el("span", null, `page ${n}`));
    wrap.appendChild(note);

    for (const b of cited.highlights[n] || []) {
      const hl = el("div", "hl");
      hl.style.left = `${b.left * 100}%`;
      hl.style.top = `${b.top * 100}%`;
      hl.style.width = `${b.width * 100}%`;
      hl.style.height = `${b.height * 100}%`;
      wrap.appendChild(hl);
    }

    body.appendChild(wrap);
    cited.observer.observe(wrap);
  }
  updateCitedCounter();
  repaintFinds("cited");
}

function loadCitedPage(wrap) {
  const n = wrap.dataset.page;
  const img = el("img");
  img.alt = `page ${n}`;
  img.src = `/api/papers/${cited.paperId}/page/${n}.png?zoom=2.2`;
  img.onload = () => {
    wrap.classList.remove("placeholder");
    wrap.querySelector(".loading-note")?.remove();
  };
  img.onerror = () => {
    wrap.classList.remove("placeholder");
    wrap.classList.add("failed");
    img.remove();
    const note = wrap.querySelector(".loading-note");
    if (note) note.textContent = `page ${n} could not be rendered`;
  };
  wrap.insertBefore(img, wrap.firstChild);
}

function goToCitedPage(n, behavior) {
  const target = $("cited-body").querySelector(`.page-wrap[data-page="${n}"]`);
  if (!target) return;
  cited.page = n;
  target.scrollIntoView({ block: "start", behavior: behavior || "smooth" });
  updateCitedCounter();
}

function updateCitedCounter() {
  $("cited-page").textContent = `${cited.page} / ${cited.pages}`;
}

/** Which page is under the top of the viewport, so the counter tracks the
 *  scroll rather than only the last button press. */
function citedScrolled() {
  const body = $("cited-body");
  const top = body.getBoundingClientRect().top;
  let current = cited.page;
  for (const wrap of body.querySelectorAll(".page-wrap")) {
    if (wrap.getBoundingClientRect().top - top <= 80) {
      current = Number(wrap.dataset.page);
    }
  }
  if (current !== cited.page) {
    cited.page = current;
    updateCitedCounter();
  }
}

function closeCited() {
  $("cited").hidden = true;
  $("splitter").hidden = true;
  document.body.classList.remove("cited-open");
  // A search put away with the pane, so reopening starts on the paper rather
  // than on somebody's last query.
  toggleFind("cited", false);
}

/* ------------------------------------------------------- pane splitter */

const MIN_PANE = 260;          // px; below this a PDF page is unreadable
const DEFAULT_SPLIT = 0.46;

/** `fraction` is the share of the reader+cited area given to the cited pane.
 *  Stored as a fraction so it survives a window resize, but applied in pixels:
 *  a percentage flex-basis resolves against `main`, which also holds the rail,
 *  and the two would drift apart. */
/** The flex row holding the reader, the splitter, the cited pane and the rail.
 *
 *  Found by tag rather than through the reader's parent: the reader gained a
 *  wrapper when the search bar arrived, and "the reader's parent" quietly
 *  stopped meaning this element -- which pinned the divider in place. */
const mainRow = () => document.querySelector("main");

function setSplit(fraction) {
  const main = mainRow();
  const usable =
    main.clientWidth - $("rail").offsetWidth - ($("splitter").offsetWidth || 7);
  if (usable <= 0) return;

  const lo = Math.min(MIN_PANE / usable, 0.5);
  const clamped = Math.min(1 - lo, Math.max(lo, fraction));
  document.documentElement.style.setProperty(
    "--cited-width", `${Math.round(clamped * usable)}px`);
  localStorage.setItem("sextant.split", String(clamped));
}

function storedSplit() {
  const saved = parseFloat(localStorage.getItem("sextant.split"));
  return Number.isFinite(saved) ? saved : DEFAULT_SPLIT;
}

function startResize(event) {
  event.preventDefault();
  const splitter = $("splitter");
  const main = mainRow();
  splitter.classList.add("dragging");
  document.body.classList.add("resizing");

  // Listeners go on window, not on the splitter with setPointerCapture.
  // Capture is the fragile part: it depends on the element still being laid
  // out and the pointer id still being valid, and when it fails it fails
  // silently -- the divider simply never moves, with no error to see.
  const move = (e) => {
    const box = main.getBoundingClientRect();
    const usable = box.width - $("rail").offsetWidth - $("splitter").offsetWidth;
    if (usable <= 0) return;
    // Distance from the pointer to the right edge of the reader+cited area,
    // measured against the same total setSplit divides by.
    setSplit((box.left + box.width - $("rail").offsetWidth - e.clientX) / usable);
  };
  const stop = () => {
    splitter.classList.remove("dragging");
    document.body.classList.remove("resizing");
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
    window.removeEventListener("blur", stop);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
  window.addEventListener("blur", stop);
}

/* ------------------------------------------------------------------ chat */

function renderChatTargets() {
  const select = $("chat-target");
  select.innerHTML = "";
  select.appendChild(new Option("The manuscript", ""));
  for (const r of state.ws.references) {
    if (r.available) select.appendChild(new Option(`${r.marker} ${r.key}`, r.key));
  }
}

async function ask(event) {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question || !state.path) return;

  const out = $("chat-out");
  out.innerHTML = "";
  out.appendChild(el("p", "hint", "thinking…"));
  say("asking Claude…");

  let result;
  try {
    result = await postJSON("/api/chat", {
      path: state.path,
      question,
      key: $("chat-target").value || null,
    });
  } catch (err) {
    out.innerHTML = "";
    out.appendChild(el("p", "err", err.message));
    say("");
    return;
  }
  say("");
  out.innerHTML = "";

  if (result.mode === "no-context") {
    out.appendChild(el("p", "hint",
      "Nothing in that paper matched. Try different wording."));
    return;
  }

  if (result.error) out.appendChild(el("p", "err", result.error));

  if (result.text) {
    out.appendChild(el("div", "answer", result.text));
  } else {
    out.appendChild(el("p", "hint",
      "No Claude backend here. Paste this grounded prompt into a Claude session."));
    const box = el("textarea");
    box.value = result.prompt;
    box.readOnly = true;
    out.appendChild(box);
    const copy = el("button", null, "Copy prompt");
    copy.onclick = () => {
      box.select();
      navigator.clipboard.writeText(result.prompt).then(() => say("copied"));
    };
    out.appendChild(copy);
  }

  const sources = el("div", "field");
  sources.appendChild(el("div", "label", "Grounded on"));
  for (const e of result.excerpts) {
    sources.appendChild(el("div", "quote", `p. ${e.page} — ${e.text.slice(0, 220)}…`));
  }
  out.appendChild(sources);
}

/* ------------------------------------------------------------------ tabs */

function switchTab(name) {
  for (const button of document.querySelectorAll("#tabs button")) {
    button.classList.toggle("active", button.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".tab")) {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  }
}

for (const button of document.querySelectorAll("#tabs button")) {
  button.onclick = () => switchTab(button.dataset.tab);
}

function stepMarker(delta) {
  if (!state.ws || !state.ws.markers.length) return;
  const current = state.ws.markers.findIndex((m) => m.id === state.selected);
  const next = Math.min(state.ws.markers.length - 1, Math.max(0, current + delta));
  selectMarker(state.ws.markers[next].id);
  document.querySelector(`.marker[data-id="${state.ws.markers[next].id}"]`)
    ?.scrollIntoView({ block: "center", behavior: "smooth" });
}

$("chat-form").onsubmit = ask;
$("update").onclick = updateFromFolder;
$("home").onclick = goHome;
$("assess-all").onclick = startAssessing;
$("reassess").onclick = reassessAll;
for (const button of document.querySelectorAll("#effort button")) {
  button.onclick = () => setEffort(button.dataset.effort);
}
paintEffort();
for (const [which, box] of [["manuscript", "find-manuscript"], ["cited", "find-cited"]]) {
  $(box).addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    if (finds[which].query === e.target.value.trim() && finds[which].hits.length) {
      stepFind(which, e.shiftKey ? -1 : 1);
    } else {
      runFind(which);
    }
  });
  $(box).addEventListener("search", () => runFind(which));
  // Escape belongs to the search while the caret is in it; the global handler
  // ignores inputs, so without this it would close the cited pane instead.
  $(box).addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    e.stopPropagation();
    toggleFind(which, false);
  });
  $(`${box}-prev`).onclick = () => stepFind(which, -1);
  $(`${box}-next`).onclick = () => stepFind(which, 1);
  $(findParts(which).lens).onclick = () => toggleFind(which);
}
$("browse-open").onclick = () => openBrowser();
// Delegated rather than bound: Home puts the reader back from EMPTY_READER,
// which replaces this button with a fresh copy, and a handler held on the
// original would decorate an element no longer on the page.
document.addEventListener("click", (e) => {
  if (e.target.closest?.("#open-document")) openBrowser();
});
$("setup-go").onclick = goFromSetup;
$("setup-back").onclick = () => {
  $("setup").hidden = true;
  if (!state.reopening) openBrowser();
};
$("browse-cancel").onclick = () => { $("browser").hidden = true; };
$("browse-jump").onsubmit = jumpToTyped;
$("addfiles").onchange = (e) => { addReferenceFiles(e.target.files); e.target.value = ""; };
$("cited-close").onclick = closeCited;
$("cited-body").addEventListener("scroll", citedScrolled, { passive: true });
$("splitter").addEventListener("pointerdown", startResize);
$("splitter").addEventListener("dblclick", () => setSplit(DEFAULT_SPLIT));
$("fetch-all").onclick = () =>
  buildLibrary(state.ws.references.filter((r) => !r.available).map((r) => r.key));

document.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
  if (e.key === "Escape") closeCited();
  if (e.key === "j") stepMarker(1);
  if (e.key === "k") stepMarker(-1);
});

window.addEventListener("resize", () => {
  if (!$("cited").hidden) setSplit(storedSplit());
});

/** Look the drop zone up each time: Home replaces it, and a captured
 *  reference would decorate an element no longer on the page. */
function bindDropzone() {
  const zone = () => document.getElementById("drop");
  for (const name of ["dragenter", "dragover"]) {
    document.addEventListener(name, (e) => {
      e.preventDefault();
      zone()?.classList.add("over");
    });
  }
  document.addEventListener("dragleave", () => zone()?.classList.remove("over"));
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    zone()?.classList.remove("over");
    const file = e.dataTransfer?.files?.[0];
    if (file) uploadFile(file);
  });
}
bindDropzone();
fetch("/api/backends").then((r) => r.json()).then((b) => {
  state.backend = Boolean(b.cli || b.api);
  $("backend").textContent = b.cli
    ? "via Claude Code"
    : b.api ? "via API key" : "no backend — prompt only";
  // Offering to spend on judgements with nothing to spend them through
  // produced one "could not reach Claude" per citation, thirty times over.
  paintAssessAll();
});
