/* The reader tour.
 *
 * The first time a manuscript opens, the parts of the reading view are
 * pointed out one at a time, on the real interface rather than in a manual.
 *
 * Passive by design. It switches the side tab to show what it describes and
 * nothing else: it never clicks a marker, fetches, or spends. A tour that
 * started a judgement would charge the reader for being shown around.
 *
 * Loaded after app.js, whose $, el and switchTab it uses.
 */

/** Remembered once the tour is finished or skipped, in this browser. */
const TOUR_SEEN = "sextant.tourSeen";

/** Room around the element pointed at, and between it and the card. */
const TOUR_PAD = 6;
const TOUR_GAP = 12;

/** Each stop, in order. One whose element is not on screen is left out
 *  rather than pointed at nothing. The last has no element and stands in the
 *  middle of the window. */
const TOUR_STOPS = [
  {
    target: ".marker",
    title: "Each box is a citation",
    text: "Its colour is what the mechanical check found. Green: the figure is "
        + "in the cited paper. Red: it appears nowhere in it. Grey: the paper "
        + "is not in the library. Faint blue: no figure to check. Once a "
        + "citation is judged, its colour is the score instead. Click one to "
        + "open the cited paper at that passage.",
  },
  {
    target: '#tabs [data-tab="refs"]',
    tab: "refs",
    title: "References",
    text: "Every paper this manuscript cites, where Sextant keeps them, and "
        + "how to get the ones that are missing.",
  },
  {
    target: ".folder",
    tab: "refs",
    title: "The references folder",
    text: "Where this manuscript's papers are kept: usually refs/ beside the "
        + "manuscript. Each paper is filed there under its citation key, so it "
        + "opens in any PDF reader as well. Click the path to copy it, or "
        + "Change\u2026 to keep them somewhere else.",
  },
  {
    target: "#refs li:not(.head)",
    tab: "refs",
    title: "One row per reference",
    text: "Numbered as the manuscript numbers them, with the citation as the "
        + "manuscript prints it. Click a row's key, the name above the "
        + "citation, to open that paper beside the manuscript. A greyed row has "
        + "no paper yet; its key shows how to find one.",
  },
  {
    target: "#refs .head",
    tab: "refs",
    title: "Score, Cited, Pages",
    text: "Score is the best judgement any of this reference's citations "
        + "earned, out of 5; hover over it for the lowest. N means no score "
        + "yet. Cited is how many times the manuscript cites it. Pages is its "
        + "length in the library, and a dash means it is not there.",
  },
  {
    target: "#refs-actions",
    tab: "refs",
    title: "Getting the missing papers",
    text: "Retry online asks the open-access sources again for every missing "
        + "paper, and Fetch on a row asks for one. For a paper they cannot "
        + "reach, download it yourself and drop it anywhere in the references "
        + "folder, then press Update from folder, or pick it with Add papers. "
        + "Each file is matched to its reference by the title and DOI on its "
        + "first page.",
  },
  {
    target: "#refs li.missing",
    tab: "refs",
    title: "A paper no source could reach",
    text: "Click its key for its DOI and links to search for it. There, "
        + "Choose the PDF files the one you pick under this reference "
        + "directly, with no title matching to get wrong.",
  },
  {
    target: '#tabs [data-tab="marker"]',
    tab: "marker",
    title: "Details",
    text: "Whatever you select. For a citation: its sentence, the figure "
        + "checked, where it was found, and judging just that one. For a "
        + "reference: every place the manuscript cites it, with its paper "
        + "opened beside the manuscript.",
  },
  {
    target: '#tabs [data-tab="chat"]',
    tab: "chat",
    title: "Ask",
    text: "A question about the manuscript or one of its papers, one at a "
        + "time: nothing carries over to the next. Claude is given only "
        + "the five passages that best match your question, and answers from "
        + "those with page numbers, or says plainly that they do not hold the "
        + "answer.",
  },
  {
    target: ".chat-controls",
    tab: "chat",
    title: "What to ask about",
    text: "The manuscript, or any paper already in the library. Under each "
        + "answer, Grounded on lists the passages it was given, so you can "
        + "check it against them. Each question is one call, through Claude "
        + "Code or an API key, and the line beside this says which; with "
        + "neither, you get the prompt to paste into Claude yourself.",
  },
  {
    target: "#effort",
    title: "Nothing is judged until you ask",
    text: "Effort sets how much of each cited paper Claude reads. Hover over "
        + "Assess to see roughly what a run would cost before you start one.",
  },
  {
    target: "#find-manuscript-toggle",
    title: "Find",
    text: "Search the manuscript or the cited paper. Search hits are blue and "
        + "evidence is amber, so a hit never passes for evidence.",
  },
  {
    target: null,
    title: "Where to look, not a verdict",
    text: "Sextant shows you where a claim sits in the paper it cites. It never "
        + "says a citation is supported: that judgement is yours. Replay this "
        + "tour from ? at any time.",
  },
];

/** The tour on screen, or null. */
let tour = null;

/** Start the tour, unless this browser has seen it already. */
function maybeStartTour() {
  if (!localStorage.getItem(TOUR_SEEN)) startTour();
}

function startTour() {
  endTour({ remember: false });
  // Handed back at the end: landing on References whatever tab the reader
  // was on lost their place.
  const returnTo = document.querySelector("#tabs button.active")?.dataset.tab || "refs";
  // A tab's parts are only on screen while that tab is. Replayed from the
  // Chat tab, the Library's were all left out as not there, so each stop's
  // tab is shown before its element is looked for.
  const stops = TOUR_STOPS.filter((stop) => {
    if (stop.tab) switchTab(stop.tab);
    return onScreen(stop);
  });
  switchTab("refs");
  if (!stops.length) return;

  const layer = el("div", "tour");
  const hole = el("div", "tour-hole");
  const card = el("div", "tour-card");
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-modal", "true");
  card.setAttribute("aria-labelledby", "tour-title");
  layer.appendChild(hole);
  layer.appendChild(card);
  document.body.appendChild(layer);

  tour = { stops, at: 0, layer, hole, card, target: null, buttons: [], returnTo };
  // On the window, while the event is captured: before the app's own keys.
  window.addEventListener("keydown", tourKeys, true);
  window.addEventListener("resize", placeTour);
  // Capture: the reader scrolls inside its own pane, not the window, and the
  // cut-out has to follow the marker when it does.
  document.addEventListener("scroll", placeTour, true);
  showStop();
}

/** Close the tour. Finishing and skipping both count as having seen it. */
function endTour({ remember = true } = {}) {
  if (!tour) return;
  window.removeEventListener("keydown", tourKeys, true);
  window.removeEventListener("resize", placeTour);
  document.removeEventListener("scroll", placeTour, true);
  tour.layer.remove();
  const { returnTo } = tour;
  tour = null;
  switchTab(returnTo);
  if (remember) localStorage.setItem(TOUR_SEEN, "1");
}

/** Forward or back one stop. Forward from the last one finishes. */
function tourStep(delta) {
  if (!tour) return;
  const at = tour.at + delta;
  if (at >= tour.stops.length) return endTour();
  if (at < 0) return;
  tour.at = at;
  showStop();
}

function tourKeys(e) {
  // Nothing reaches the page underneath while the tour stands over it: j and
  // k stepped through markers behind the card, switched the tab under it and
  // fetched for each. Enter and Space still press the card's own buttons;
  // that is their default action, which this leaves alone.
  e.stopImmediatePropagation();
  if (e.key === "Escape") endTour();
  else if (e.key === "ArrowRight") tourStep(1);
  else if (e.key === "ArrowLeft") tourStep(-1);
  else if (e.key === "Tab") keepFocusInCard(e);
}

/** Tab and Shift-Tab go round the card's buttons. Left to the page, focus
 *  walked onto the buttons behind the layer, and Enter pressed them. */
function keepFocusInCard(e) {
  e.preventDefault();
  const { buttons } = tour;
  const at = buttons.indexOf(document.activeElement);
  const step = e.shiftKey ? -1 : 1;
  buttons[at === -1 ? 0 : (at + step + buttons.length) % buttons.length].focus();
}

/** Is this stop's element there to point at? display:none leaves no box. */
function onScreen(stop) {
  if (!stop.target) return true;
  const node = document.querySelector(stop.target);
  if (!node || node.hidden) return false;
  const box = node.getBoundingClientRect();
  return box.width > 0 && box.height > 0;
}

function tourButton(cls, label, onclick) {
  const button = el("button", cls, label);
  button.type = "button";
  button.onclick = onclick;
  return button;
}

function showStop() {
  const { stops, at, card } = tour;
  const stop = stops[at];
  if (stop.tab) switchTab(stop.tab);
  const target = stop.target ? document.querySelector(stop.target) : null;
  if (target) target.scrollIntoView({ block: "center", inline: "nearest" });

  card.innerHTML = "";
  card.appendChild(el("div", "tour-count", `${at + 1} / ${stops.length}`));
  const title = el("h2", "tour-title", stop.title);
  title.id = "tour-title";
  card.appendChild(title);
  card.appendChild(el("p", "tour-text", stop.text));

  const buttons = [tourButton("tour-skip", "Skip tour", () => endTour())];
  if (at > 0) buttons.push(tourButton("tour-back", "Back", () => tourStep(-1)));
  const next = tourButton("tour-next", at === stops.length - 1 ? "Finish" : "Next",
                          () => tourStep(1));
  buttons.push(next);
  const row = el("div", "tour-row");
  for (const button of buttons) row.appendChild(button);
  card.appendChild(row);
  tour.buttons = buttons;

  tour.target = target;
  tour.layer.classList.toggle("tour-centre", !target);
  placeTour();
  next.focus();
}

/** The cut-out over the element, and the card below it -- or above, when
 *  only above has room, or whichever side has more when neither does --
 *  kept inside the window either way. */
function placeTour() {
  if (!tour) return;
  const { hole, card, target } = tour;
  if (!target) {
    hole.hidden = true;
    card.style.left = card.style.top = "";
    return;
  }
  const box = target.getBoundingClientRect();
  // Inside the window: against an edge, as the Chat tab is, the padding ran
  // past it and took the outline on that side with it.
  const x0 = Math.max(0, box.left - TOUR_PAD);
  const y0 = Math.max(0, box.top - TOUR_PAD);
  const x1 = Math.min(window.innerWidth, box.left + box.width + TOUR_PAD);
  const y1 = Math.min(window.innerHeight, box.top + box.height + TOUR_PAD);
  hole.hidden = false;
  hole.style.left = `${x0}px`;
  hole.style.top = `${y0}px`;
  hole.style.width = `${x1 - x0}px`;
  hole.style.height = `${y1 - y0}px`;

  const height = card.offsetHeight;
  const below = window.innerHeight - box.bottom - TOUR_PAD - TOUR_GAP;
  const above = box.top - TOUR_PAD - TOUR_GAP;
  // With room on neither side, pinning the card to the top edge laid it over
  // the very element it was describing. The roomier side overlaps it least.
  const under = height <= below || (height > above && below >= above);
  const top = under ? box.bottom + TOUR_PAD + TOUR_GAP : above - height;
  const left = Math.min(box.left, window.innerWidth - card.offsetWidth - TOUR_GAP);
  card.style.top = `${Math.max(TOUR_GAP, Math.min(top, window.innerHeight - height - TOUR_GAP))}px`;
  card.style.left = `${Math.max(TOUR_GAP, left)}px`;
}

$("tour-open").onclick = () => startTour();
