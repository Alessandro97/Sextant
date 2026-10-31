/* The reader tour, driven stop by stop on a fake page.
 * Printed as `label :: fact` so the test can read each one. */
const fs = require("fs");
const vm = require("vm");
const { loadApp } = require("./fake_dom.js");

loadApp();

let focused = null;
let tab = null;

/* Nodes that remember what the tour did to them, which fake_dom's do not:
   classes, children cleared by innerHTML = "", removal, focus. */
const made = (tag) => {
  const classes = new Set();
  return {
    tag, kids: [], style: {}, dataset: {}, attrs: {}, hidden: false, removed: false,
    id: "", type: "", onclick: null, _text: "",
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, on) => {
        const want = on === undefined ? !classes.has(c) : Boolean(on);
        if (want) classes.add(c); else classes.delete(c);
        return want;
      },
      contains: (c) => classes.has(c),
    },
    set className(v) { classes.clear(); for (const c of String(v).split(/\s+/)) if (c) classes.add(c); },
    get className() { return [...classes].join(" "); },
    set textContent(v) { this._text = String(v); },
    get textContent() { return this._text; },
    set innerHTML(v) { if (v === "") this.kids = []; },
    get innerHTML() { return ""; },
    appendChild(k) { this.kids.push(k); return k; },
    remove() { this.removed = true; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] ?? null; },
    focus() { focused = this; document.activeElement = this; },
    scrollIntoView() {},
    getBoundingClientRect: () => ({ top: 100, left: 100, width: 40, height: 16,
                                    bottom: 116, right: 140 }),
    offsetWidth: 340, offsetHeight: 160,
  };
};

/* What the tour can point at. The effort selector is in the page but
   display:none, as when no manuscript is open: no box at all. The Library's
   parts only have a box while the Library tab is the one showing, as in the
   page, where the other tabs' panels are display:none. Nothing is missing
   from this library, so there is no greyed row to point at. */
const none = () => ({ top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 });
const effort = made("div");
effort.getBoundingClientRect = none;
const inTab = (name) => {
  const node = made("div");
  const box = node.getBoundingClientRect;
  node.getBoundingClientRect = () => (tab === name ? box() : none());
  return node;
};
const inLibrary = () => inTab("refs");
const targets = {
  ".marker": made("div"),
  '#tabs [data-tab="refs"]': made("button"),
  ".folder": inLibrary(),
  "#refs li:not(.head)": inLibrary(),
  "#refs .head": inLibrary(),
  "#refs-actions": inLibrary(),
  '#tabs [data-tab="marker"]': made("button"),
  '#tabs [data-tab="chat"]': made("button"),
  ".chat-controls": inTab("chat"),
  "#effort": effort,
  "#find-manuscript-toggle": made("button"),
};

const store = new Map();
const listeners = {};
document.querySelector = (sel) => targets[sel] ?? null;
document.createElement = (tag) => made(tag);
document.body = made("body");
document.addEventListener = (type, fn) => { (listeners[type] ??= []).push(fn); };
document.removeEventListener = (type, fn) => {
  listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
};
window.addEventListener = (type, fn, capture) => {
  if (type === "keydown") (listeners.windowKeydown ??= []).push(fn);
};
window.removeEventListener = (type, fn) => {
  if (type === "keydown") {
    listeners.windowKeydown = (listeners.windowKeydown || []).filter((f) => f !== fn);
  }
};
window.innerHeight = 900;
global.localStorage = {
  getItem: (k) => store.get(k) ?? null,
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
global.switchTab = (name) => { tab = name; };

new vm.Script(fs.readFileSync("src/sextant/web/static/tour.js", "utf8"),
              { filename: "tour.js" }).runInThisContext();

const fact = (label, value) => console.log(`${label} :: ${value}`);
const layer = () => document.body.kids.find((k) => k.classList.contains("tour") && !k.removed);
const card = () => layer().kids.find((k) => k.classList.contains("tour-card"));
const part = (cls) => card().kids.find((k) => k.classList.contains(cls));
const title = () => part("tour-title").textContent;
const buttons = () => part("tour-row").kids.map((b) => b.textContent);
const press = (label) => part("tour-row").kids.find((b) => b.textContent === label).onclick();
/* A key press as the page sees it: the window's listeners first, as capture
   runs, and the app's own only if nothing stopped it on the way. */
const key = (k, shift = false) => {
  const event = { key: k, shiftKey: shift, stopped: false, prevented: false,
                  stopPropagation() { this.stopped = true; },
                  stopImmediatePropagation() { this.stopped = true; },
                  preventDefault() { this.prevented = true; } };
  [...(listeners.windowKeydown || [])].forEach((f) => f(event));
  if (!event.stopped) [...(listeners.keydown || [])].forEach((f) => f(event));
  return event;
};
const opened = () => (layer() ? "yes" : "no");

try {
  maybeStartTour();
  fact("first", title());
  fact("count", part("tour-count").textContent);
  fact("back on first", buttons().includes("Back") ? "yes" : "no");
  fact("focus", focused ? focused.textContent : "nothing");
  fact("card at", `${card().style.left} ${card().style.top}`);
  const hole = layer().kids.find((k) => k.classList.contains("tour-hole"));
  fact("hole at", `${hole.style.left} ${hole.style.top} ${hole.style.width} ${hole.style.height}`);

  press("Next");
  fact("next", title());
  fact("tab", tab);
  press("Back");
  fact("back", title());

  const titles = [title()];
  while (!buttons().includes("Finish")) { press("Next"); titles.push(title()); }
  fact("titles", titles.join(" | "));
  fact("last button", buttons().at(-1));
  fact("centred", layer().classList.contains("tour-centre") ? "yes" : "no");
  press("Finish");
  fact("finish", `open=${opened()} seen=${localStorage.getItem("sextant.tourSeen")} tab=${tab}`);

  store.clear();
  startTour();
  key("ArrowRight");
  fact("arrow", title());
  fact("j during the tour", key("j").stopped ? "stopped" : "reached the app");
  const buttonsNow = part("tour-row").kids;
  buttonsNow.at(-1).focus();
  key("Tab");
  fact("tab from the last button", focused === buttonsNow[0] ? "first button" : "left the card");
  buttonsNow[0].focus();
  key("Tab", true);
  fact("shift-tab from the first button", focused === buttonsNow.at(-1) ? "last button" : "left the card");
  key("Escape");
  fact("escape", `open=${opened()} seen=${localStorage.getItem("sextant.tourSeen")} `
               + `keys=${(listeners.windowKeydown || []).length}`);

  // Started from the Ask tab, the tour hands it back.
  const active = made("button"); active.dataset.tab = "chat";
  targets["#tabs button.active"] = active;
  tab = "chat";
  startTour();
  endTour();
  fact("tab after a tour started on Ask", tab);
  delete targets["#tabs button.active"];

  maybeStartTour();
  fact("seen does not start", opened());
  tab = "chat";
  startTour();
  fact("replay", layer() ? title() : "nothing");
  fact("replay from another tab", part("tour-count").textContent);

  // A tall card and no room for it on either side, as on a short window: it
  // was pinned to the top edge, over the very element it was describing.
  endTour({ remember: false });
  window.innerHeight = 700;
  targets[".marker"].getBoundingClientRect = () => ({ top: 290, left: 300, width: 390,
                                                      height: 88, bottom: 378, right: 690 });
  document.createElement = (t) => Object.assign(made(t), { offsetHeight: 312 });
  startTour();
  fact("cramped card top", card().style.top);

  // An element against the window's right edge, as the Chat tab is: the
  // cut-out ran past it and lost its outline on that side.
  endTour({ remember: false });
  window.innerWidth = 1400;
  targets[".marker"].getBoundingClientRect = () => ({ top: 50, left: 1262, width: 138,
                                                      height: 42, bottom: 92, right: 1400 });
  startTour();
  const edge = layer().kids.find((k) => k.classList.contains("tour-hole"));
  fact("hole at the edge", `${edge.style.left} ${edge.style.width}`);
  fact("card at the edge", card().style.left);

  // The other two edges the cut-out can run past.
  const holeOf = () => layer().kids.find((k) => k.classList.contains("tour-hole"));
  endTour({ remember: false });
  targets[".marker"].getBoundingClientRect = () => ({ top: 50, left: 0, width: 138,
                                                      height: 42, bottom: 92, right: 138 });
  startTour();
  fact("hole at the left edge", `${holeOf().style.left} ${holeOf().style.width}`);
  endTour({ remember: false });
  targets[".marker"].getBoundingClientRect = () => ({ top: 658, left: 300, width: 100,
                                                      height: 42, bottom: 700, right: 400 });
  startTour();
  fact("hole at the bottom edge", `${holeOf().style.top} ${holeOf().style.height}`);

  // Back from the first stop goes nowhere, and does not break the tour.
  key("ArrowLeft");
  fact("left on first", title());
  key("ArrowRight");
  fact("then right", title());

  // Replayed from Ask, the tour itself opens on References.
  endTour({ remember: false });
  tab = "chat";
  startTour();
  fact("tab at start", tab);

  // An element with width but no height is no more there than none at all.
  endTour({ remember: false });
  effort.getBoundingClientRect = () => ({ top: 10, left: 10, width: 120, height: 0,
                                          bottom: 10, right: 130 });
  startTour();
  fact("flat element count", part("tour-count").textContent);
  effort.getBoundingClientRect = none;
} catch (e) {
  fact("THREW", `${e.name}: ${e.message} ${(e.stack || "").split("\n")[1]}`);
}
