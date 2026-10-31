"""Static checks on the browser code.

There is no JS test runner here, and a missing helper is invisible to the
Python suite: `showCited` called an undefined `get()` and every "open cited
paper" click failed with a ReferenceError while all 371 tests stayed green.
These checks are cheap and catch exactly that class of mistake.
"""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "sextant" / "web" / "static"
#: Both scripts, as one: tour.js calls into app.js, so a helper defined in
#: one and called in the other is defined as far as the page is concerned.
JS = "\n".join((STATIC / name).read_text() for name in ("app.js", "tour.js"))
HTML = (STATIC / "index.html").read_text()

_BUILTINS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "await",
    "function", "fetch", "alert", "parseInt", "parseFloat", "encodeURIComponent",
    "async", "await", "new", "delete", "void",
    "decodeURIComponent", "setTimeout", "clearTimeout", "setInterval",
    "clearInterval", "isNaN", "String",
    "Number", "Boolean", "Array", "Object", "JSON", "Math", "Promise",
}


def _defined() -> set[str]:
    names = set(re.findall(r"^(?:async )?function (\w+)", JS, re.M))
    names |= set(re.findall(r"^const (\w+)\s*=", JS, re.M))
    names |= set(re.findall(r"^\s+const (\w+)\s*=", JS, re.M))
    return names


def test_every_helper_called_at_top_level_is_defined():
    called = set(re.findall(r"(?<![.\w$])([a-z][A-Za-z0-9_]*)\s*\(", JS))
    missing = called - _defined() - _BUILTINS
    # Locally-scoped callbacks are filtered by requiring the name to appear
    # with parentheses more than once, which a one-off local rarely does.
    real = {n for n in missing if len(re.findall(rf"(?<![.\w$]){n}\s*\(", JS)) > 1}
    assert not real, f"called but never defined: {sorted(real)}"


def test_the_helpers_the_cited_pane_depends_on_exist():
    for name in ("get", "postJSON", "showCited", "renderCited", "closeCited",
                 "goToCitedPage", "loadCitedPage", "openReference", "runAssess"):
        assert name in _defined(), f"{name} is missing from app.js"


def test_every_element_id_the_script_reaches_for_exists_in_the_html():
    wanted = set(re.findall(r'\$\("([^"]+)"\)', JS))
    present = set(re.findall(r'id="([^"]+)"', HTML))
    missing = wanted - present
    assert not missing, f"app.js reaches for ids not in index.html: {sorted(missing)}"


def test_the_html_loads_no_remote_resources():
    """The viewer must work with the network off."""
    remote = re.findall(r'(?:src|href)="(https?://[^"]+)"', HTML)
    assert remote == [], f"remote assets would break offline use: {remote}"


@pytest.mark.parametrize("pair", [("{", "}"), ("(", ")"), ("[", "]")])
def test_brackets_balance(pair):
    opener, closer = pair
    assert JS.count(opener) == JS.count(closer), f"unbalanced {opener}{closer}"


def test_the_busy_overlay_is_always_dismissed():
    """An overlay stuck on is worse than no overlay: it hides a working app.
    Every path that raises it must be able to lower it."""
    raised = len(re.findall(r"(?<![.\w])busy\(", JS))
    lowered = len(re.findall(r"(?<![.\w])idle\(\)", JS))
    assert raised > 0, "no loading overlay is being shown at all"
    assert lowered >= raised, f"busy() raised {raised}x but idle() called {lowered}x"


def test_a_failed_page_render_stops_the_spinner():
    """Otherwise a broken page spins forever and reads as a slow network."""
    assert JS.count("img.onerror") >= 2, "page images need an error path"
    assert "could not be rendered" in JS


def test_page_placeholders_carry_a_spinner():
    assert "loading-note" in JS and "loading-note" in (STATIC / "app.css").read_text()
    assert "spinner" in (STATIC / "app.css").read_text()


def test_the_layout_does_not_hardcode_a_header_height():
    """`height: calc(100vh - 3.2rem)` guessed the header height. Once the
    header grew, main hung below the viewport and every inner scroll container
    ran off-screen -- which is why neither pane scrolled."""
    css = (STATIC / "app.css").read_text()
    assert "calc(100vh" not in css, "header height must not be guessed"
    assert re.search(r"main\s*\{[^}]*flex:\s*1", css), "main must flex to fill"


def test_every_scrolling_pane_can_actually_shrink():
    """A flex child without min-height:0 refuses to shrink below its content,
    so overflow-y never engages."""
    css = (STATIC / "app.css").read_text()
    for selector in ("#reader", "#cited-body", ".tab"):
        block = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
        assert block, f"{selector} rule not found"
        body = block.group(1)
        assert "overflow-y: auto" in body, f"{selector} should scroll"
        assert "min-height: 0" in body, f"{selector} needs min-height: 0 to scroll"


def test_the_splitter_exists_and_is_draggable():
    assert 'id="splitter"' in HTML
    assert "startResize" in JS
    assert "col-resize" in (STATIC / "app.css").read_text()


def test_the_splitter_clamps_so_a_pane_cannot_vanish():
    assert "MIN_PANE" in JS
    assert "Math.min" in JS and "Math.max" in JS


def test_the_splitter_is_hidden_until_a_cited_paper_is_open():
    assert 'id="splitter" hidden' in HTML
    assert JS.count('$("splitter").hidden = false') >= 1
    assert JS.count('$("splitter").hidden = true') >= 1


def test_the_split_is_applied_in_pixels_not_a_percentage():
    """A percentage flex-basis resolves against `main`, which also contains the
    rail, so it would drift from the fraction the drag computed."""
    assert re.search(r'--cited-width["\']?,\s*`\$\{[^`]*\}px`', JS), \
        "the split must be set in px"


def test_the_split_survives_a_window_resize():
    assert 'addEventListener("resize"' in JS
    assert "storedSplit" in JS


def test_the_cited_pane_renders_every_page_not_just_one():
    """One page at a time with arrow buttons cannot be scrolled through, which
    is the only way anyone actually reads a paper."""
    body = JS[JS.index("function renderCited()"):JS.index("function loadCitedPage")]
    assert "for (let n = 1; n <= cited.pages" in body, "must build all pages"
    assert "IntersectionObserver" in body, "and load them lazily"


def test_the_cited_pane_lazy_loads_against_its_own_scroll_container():
    """rootMargin against the document would load every page immediately."""
    body = JS[JS.index("function renderCited()"):JS.index("function loadCitedPage")]
    assert "root: body" in body


def test_the_page_counter_follows_the_scroll():
    assert "citedScrolled" in JS
    assert 'addEventListener("scroll", citedScrolled' in JS


def test_opening_at_a_highlight_scrolls_there():
    assert "goToCitedPage(cited.page" in JS


def test_the_cited_pane_has_no_page_arrows():
    """Scrolling is the only way to move through it, so buttons that duplicate
    the scrollbar are just two more things that can disagree with it."""
    # Exact ids: the search bar has find-cited-prev, which contains the old
    # name as a substring.
    assert 'id="cited-prev"' not in HTML and 'id="cited-next"' not in HTML
    assert "stepCited" not in JS


def test_the_page_counter_survives_the_arrows_being_removed():
    """It reads out the scroll position, so it is still worth showing."""
    assert 'id="cited-page"' in HTML
    assert "updateCitedCounter" in JS


def test_the_rail_cannot_be_widened_by_its_own_contents():
    """A flex item's automatic minimum size is its min-content width, and that
    overrides flex-basis. Without min-width:0 a single long reference title
    pushed the rail several times past 26rem -- and only on the Library tab,
    because Marker and Chat hold nothing that wide."""
    css = (STATIC / "app.css").read_text()
    # Anchored: "body.has-manuscript #rail { display: flex }" is a different
    # rule and matching it instead told us nothing.
    rail = re.search(r"^#rail\s*\{([^}]*)\}", css, re.M)
    assert rail and "min-width: 0" in rail.group(1), \
        "#rail needs min-width: 0 or its content sets its width"
    assert re.search(r"#rail,\s*#rail \*\s*\{[^}]*min-width:\s*0", css), \
        "descendants need it too, or a nested flex child re-introduces it"


def test_the_scrolling_tab_panels_cannot_be_widened_either():
    css = (STATIC / "app.css").read_text()
    tab = re.search(r"^\.tab\s*\{([^}]*)\}", css, re.M)
    assert tab and "min-width: 0" in tab.group(1)


def test_long_reference_keys_wrap_rather_than_stretch():
    css = (STATIC / "app.css").read_text()
    assert "overflow-wrap: anywhere" in css


def test_the_cited_pane_highlights_every_page_that_has_a_passage():
    """One page's worth of boxes would show only the passage we opened at,
    leaving the rest of the assessment unevidenced."""
    assert "cited.highlights" in JS
    assert "cited.boxPage" not in JS, "single-page highlight state should be gone"
    assert "cited.boxes" not in JS


def test_cited_passages_are_clickable_and_navigate():
    body = JS[JS.index("function renderMarkerCard"):
              JS.index("async function openMarkerEvidence")]
    assert "goToCitedPage(q.page)" in body, "clicking a passage must jump to it"
    assert "quote passage clickable" in body


def test_a_passage_without_geometry_is_not_highlighted():
    """A highlight we could not confirm is exactly what the project refuses."""
    body = JS[JS.index("function renderMarkerCard"):
              JS.index("async function openMarkerEvidence")]
    assert "q.boxes && q.boxes.length" in body


def test_the_panel_is_hidden_until_a_manuscript_is_open():
    """An empty sidebar beside a drop zone is a promise of nothing."""
    css = (STATIC / "app.css").read_text()
    assert re.search(r"#rail,\s*#splitter\s*\{[^}]*display:\s*none", css)
    assert "body.has-manuscript #rail { display: flex; }" in css


def test_the_drop_zone_uses_the_whole_window_before_anything_is_open():
    css = (STATIC / "app.css").read_text()
    # The reader centres its one child; the drop zone sizes itself.
    assert "body:not(.has-manuscript) #reader" in css
    reader = re.search(r"body:not\(\.has-manuscript\) #reader\s*\{([^}]*)\}", css)
    assert reader and "center" in reader.group(1)


def test_the_manuscript_stage_is_entered_and_left():
    assert 'classList.add("has-manuscript")' in JS
    assert 'classList.remove("has-manuscript")' in JS


def test_a_failed_open_returns_to_the_drop_zone():
    body = JS[JS.index("function showReaderError"):JS.index("async function openManuscript")]
    assert 'classList.remove("has-manuscript")' in body
    assert "closeCited()" in body


def test_a_verified_quantity_links_to_the_page_it_was_found_on():
    body = JS[JS.index("async function openMarkerEvidence"):
              JS.index("function scoreChip")]
    assert "goToCitedPage(hit.page)" in body


def test_that_link_is_relocated_before_it_is_followed():
    """Opening at a highlight we did not just confirm would break the one rule
    the project runs on."""
    body = JS[JS.index("async function openMarkerEvidence"):
              JS.index("function scoreChip")]
    assert "/locate?q=" in body
    assert "hit.found" in body


def test_selecting_a_marker_asks_for_its_context_once():
    """Each call rebuilds the workspace and re-extracts every cited PDF --
    including a 146-page specification. Asking twice is not free."""
    assert JS.count('postJSON("/api/marker/occurrences"') == 1


def test_sibling_navigation_exists_for_a_reference_cited_more_than_once():
    assert "addSiblingNav" in JS
    assert "citation ${data.position + 1} of" in JS


def test_the_cited_paper_shows_one_entry_per_quoted_passage():
    """Replaces the "every occurrence of the quantity" list: a passage the
    model relied on earns a row; the twentieth appearance of "50 km" does
    not."""
    body = JS[JS.index("function renderMarkerCard"):
              JS.index("async function openMarkerEvidence")]
    assert "for (const q of quotes)" in body
    assert "goToCitedPage(q.page)" in body


def test_references_can_be_added_from_the_browser():
    assert 'id="addfiles"' in HTML
    assert "addReferenceFiles" in JS


def test_an_unfetched_reference_offers_somewhere_to_look():
    assert "showLookup" in JS
    assert "scholar.google.com" in JS and "openalex.org" in JS


def test_marker_navigation_is_rendered_for_every_marker():
    """It once sat after an early return, so the markers whose paper is
    missing -- the ones most in need of stepping through -- never got it. The
    panel now has no early returns at all."""
    # selectMarker's own body: to its closing brace, not to whatever function
    # happens to be declared next.
    start = JS.index("async function selectMarker")
    body = JS[start:JS.index("\n}\n", start)]
    assert "addSiblingNav(panel, marker, context)" in body
    assert "return;" not in body.split("addSiblingNav")[1], "no exit after the nav"


def test_there_is_a_way_back_to_the_reference():
    body = JS[JS.index("function addSiblingNav"):JS.index("function labelled")]
    assert 'el("button", "back"' in body
    assert "openReference(reference)" in body


def test_the_way_back_exists_even_for_a_reference_cited_once():
    body = JS[JS.index("function addSiblingNav"):JS.index("function labelled")]
    assert "cited once" in body, "a single citation still needs a route back"


def test_the_form_asks_for_both_folders():
    assert 'id="path"' in HTML and 'id="refsdir"' in HTML


def test_the_convert_notice_carries_its_own_button():
    """Telling someone to press a differently-named button elsewhere is one
    indirection too many."""
    body = JS[JS.index("const stuck = state.ws.unconverted"):
              JS.index("$(\"folder-hint\").textContent")]
    assert "convertPicker(stuck)" in body
    assert "Press Update" not in JS, "the notice should act, not instruct"


def test_converting_asks_which_documents_rather_than_how_many():
    """"Convert 4 documents" made the reader pay for three conversions they
    did not want to get the one they did -- and a long Word specification is tens
    of seconds each. The button opens the list; the reader confirms."""
    picker = JS[JS.index("function convertPicker("):
                JS.index("async function convertDocuments")]

    assert 'tick.type = "checkbox"' in picker, "each document is choosable"
    assert "tick.checked = true" in picker, "opting out, not in"
    assert "convertDocuments(chosen()" in picker, "it converts the selection"

    sends = JS[JS.index("async function convertDocuments"):
               JS.index("async function updateFromFolder")]
    assert "convert: names" in sends, "the server is told which, not just that"


def test_converting_also_matches_what_it_converted():
    """A converted PDF nobody filed is not progress."""
    body = JS[JS.index("async function convertDocuments"):
              JS.index("async function updateFromFolder")]
    assert "/api/workspace/rescan" in body
    assert "openManuscript" in body


def test_a_manuscript_can_be_chosen_by_real_path_without_typing():
    """A browser file picker hands over bytes and a filename, never a folder.
    The server is on the same machine and can supply the path."""
    assert 'id="browse-open"' in HTML and 'id="browser"' in HTML
    assert "openBrowser" in JS and "chooseManuscript" in JS


def test_choosing_a_manuscript_proposes_refs_beside_it():
    body = JS[JS.index("async function chooseManuscript"):
              JS.index("async function goFromSetup")]
    assert "/refs" in body, "the proposal is refs/ next to the manuscript"
    assert '$("refsdir").value = proposed' in body


def test_there_is_one_way_in():
    """Two entry points differed only by a browser limitation nobody should
    have to reason about."""
    assert 'id="browse-open"' in HTML
    assert 'id="file"' not in HTML, "the separate upload picker is gone"
    assert "openByPath" not in JS, "the inline path form is gone"


def test_the_setup_step_shows_the_folder_before_acting_on_it():
    """The folder is the decision that has gone wrong twice. Show it first."""
    assert 'id="setup"' in HTML
    assert 'id="refsdir"' in HTML and 'id="setup-go"' in HTML
    body = JS[JS.index("async function chooseManuscript"):JS.index("async function goFromSetup")]
    assert '$("setup").hidden = false' in body
    assert "openManuscript" not in body, "nothing opens until Go"


def test_go_creates_the_folder_only_because_the_reader_saw_it():
    """The setup step is the confirmation; Go acts on what was shown."""
    body = JS[JS.index("async function goFromSetup"):JS.index("function showReaderError")]
    assert "settleLibrary(wanted)" in body
    assert "create: true" in body


def test_the_cited_pane_counts_citations_in_words_and_only_when_it_helps():
    """"cited 1x" states what the reader just did, in shorthand, in a pane
    that otherwise speaks in sentences. The count is worth saying only when
    there is more than one place to go back to."""
    body = JS[JS.index("if (reference.paper_id) {"):]
    call = body[:body.index("showCited(") + 200]

    assert "×" not in call, "the multiplication sign reads as jargon here"
    assert "cited ${sites.length} times" in call
    assert "sites.length > 1" in call, "one citation earns no count"


def test_rows_toggled_by_hidden_never_claim_a_display_outright():
    """`hidden` is a user-agent rule, and an author rule beats it whatever the
    specificity. `display: flex` on these rows therefore pinned them open
    however often the JS set .hidden: both find bars stood open for good, and
    the Library actions stood on the empty tab. They may take a display only
    in the state where they are shown."""
    css = (STATIC / "app.css").read_text()

    for name in ("#reader-bar", ".findrow", "#refs-actions", ".convert-form",
                 ".effort"):
        block = css[css.index(f"{name} {{"):css.index("}", css.index(f"{name} {{"))]
        assert "display:" not in block, f"{name} must not set display outright"
        assert re.search(re.escape(name) + r":not\(\[hidden\]\)[^{]*\{[^}]*display\s*:", css), \
            f"{name} never claims a display for the state where it is shown"


def test_the_library_folder_can_be_changed_where_it_is_named():
    """The panel named the folder but offered no way to move it: changing your
    mind meant going back through the file browser and reopening. Change
    reuses the card that chose it in the first place, so there are not two
    folder editors to disagree with each other."""
    assert "chooseManuscript(state.path, { reopening: true })" in JS

    # Reached this way it is not an opening, and it must not say it is.
    body = JS[JS.index("async function chooseManuscript"):JS.index("async function goFromSetup")]
    assert '$("setup-what").textContent' in body
    assert 'id="setup-what"' in HTML

    # Back belongs to where you came from, which is the reader, not the browser.
    assert "if (!state.reopening) openBrowser();" in JS


def test_a_queued_assessment_says_so_rather_than_showing_an_inert_button():
    """An inert button looks the same whether the pass is running, finished,
    or never started."""
    body = JS[JS.index("async function runAssess"):JS.index("function labelled")]
    assert "assess/progress" in body
    assert "queued" in body, "a waiting reader should be told it is coming"
    assert "state.assessRetry" in body, "it should come back for the result"


def test_the_picker_accepts_a_pasted_path():
    """Clicking down from home was three or four steps every time, with no way
    to paste a location already known."""
    assert 'id="browse-path"' in HTML and 'id="browse-jump"' in HTML
    body = JS[JS.index("async function jumpToTyped"):JS.index("async function listFolder")]
    assert 'endsWith(".pdf")' in body, "a pasted PDF path should open it directly"
    assert "listFolder(typed)" in body


def test_the_picker_offers_recent_folders():
    assert 'id="browse-shortcuts"' in HTML
    assert "renderShortcuts" in JS and "sextant.recentDirs" in JS


def test_the_palette_is_defined_once():
    """Colours scattered through the file drift apart. One definition means
    a status hue means the same thing everywhere it appears."""
    css = (STATIC / "app.css").read_text()
    assert ":root" in css
    for token in ("--ink", "--accent", "--ok", "--warn", "--bad", "--line"):
        assert token in css, f"{token} should be a variable"


def test_every_status_has_a_marker_colour_and_a_badge_colour():
    """A status the reader can see on the page but not in the panel, or the
    other way round, reads as a bug."""
    css = (STATIC / "app.css").read_text()
    for status in ("verified", "not-found", "no-source", "no-claim"):
        assert f".m-{status}" in css, f"no marker colour for {status}"
        assert f".b-{status}" in css, f"no badge colour for {status}"


def test_every_assessment_verdict_has_a_badge_colour():
    css = (STATIC / "app.css").read_text()
    for verdict in ("supports", "related", "unrelated", "unclear"):
        assert f".b-{verdict}" in css, f"no badge colour for {verdict}"


def test_there_is_a_way_back_to_the_start():
    assert 'id="home"' in HTML
    body = JS[JS.index("function goHome()"):JS.index("function showReaderError")]
    assert "EMPTY_READER" in body, "the drop zone must be restored, not rebuilt"
    assert 'classList.remove("has-manuscript")' in body
    assert "closeCited()" in body


def test_home_does_not_stack_duplicate_drop_handlers():
    """They are on `document`, so rebinding on every visit accumulates them."""
    calls = len(re.findall(r"(?<!function )bindDropzone\(\)", JS))
    assert calls == 1, f"bindDropzone is invoked {calls} times"


def test_home_stops_the_background_timers():
    body = JS[JS.index("function goHome()"):JS.index("function showReaderError")]
    assert "clearInterval(state.assessTimer)" in body
    assert "clearTimeout(state.assessRetry)" in body


def test_no_selector_is_defined_twice_at_the_top_level():
    """A second rule for the same selector shadows the first in every test
    that reads CSS by regex, and hides which one is actually in force. It has
    caught #rail, .tab and #cited-body already."""
    css = (STATIC / "app.css").read_text()
    top_level = re.findall(r"^([#.][\w-]+)\s*\{", css, re.M)
    duplicates = {s for s in top_level if top_level.count(s) > 1}
    assert not duplicates, f"defined more than once: {sorted(duplicates)}"


def _specificity(selector: str) -> tuple[int, int, int]:
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]+\]", selector))
    elements = len(re.findall(r"(?:^|[\s>+~])([a-z]+[\w-]*)", selector))
    return (ids, classes, elements)


def _winning_background(css: str, target: str) -> tuple[tuple, str] | None:
    """The background the browser will actually use for `target`."""
    best, chosen = (-1, -1, -1), None
    for block in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selectors, body = block.group(1), block.group(2)
        found = re.search(r"background(?:-color)?:\s*([^;]+)", body)
        if not found:
            continue
        for selector in (s.strip() for s in selectors.split(",")):
            if target not in selector or ":hover" in selector:
                continue
            spec = _specificity(selector)
            if spec >= best:
                best, chosen = spec, found.group(1).strip()
    return (best, chosen) if chosen else None


def test_the_primary_buttons_are_not_white_on_white():
    """"#setup .row button" is one id, one class and one element; a bare
    "#setup-go" is one id and loses to it. Go kept its white text and took the
    generic near-white background, which made it invisible."""
    css = (STATIC / "app.css").read_text()

    for button in ("#setup-go", "#browse-open"):
        spec, background = _winning_background(css, button)
        assert "var(--accent)" in background or "var(--glow)" in background, (
            f"{button} resolves to background {background!r}; a white label "
            "on that is unreadable"
        )


def test_a_primary_button_outranks_the_generic_button_rule():
    css = (STATIC / "app.css").read_text()
    generic = _specificity("#setup .row button")

    spec, _ = _winning_background(css, "#setup-go")

    assert spec > generic, "the generic rule would win and blank the button"


def test_the_assessment_is_shown_without_pressing_anything():
    """Both buttons repeated work already done: the paper opens when a marker
    is selected, and the judgement was made when the manuscript opened."""
    assert "Assess relevance" not in HTML
    body = JS[JS.index("async function selectMarker"):JS.index("async function runAssess")]
    assert 'el("button", "assess-btn"' not in body
    assert 'el("button", null, "Open cited paper")' not in body


def test_the_panel_holds_exactly_the_five_sections():
    """Score, assessment, the sentence in each document, and a note. Anything
    else was competing with them for attention."""
    body = JS[JS.index("function renderMarkerCard"):
              JS.index("async function openMarkerEvidence")]
    for section in ("scoreBadge", '"Assessment"', "Manuscript \u00b7 p.",
                    "cited paper", '"Note"'):
        assert section in body, f"missing {section}"


def test_the_panel_dropped_what_was_not_asked_for():
    body = JS[JS.index("function renderMarkerCard"):
              JS.index("async function openMarkerEvidence")]
    for gone in ('"Checked"', "other-passages", "passages searched",
                 "assessed on open"):
        assert gone not in body, f"{gone} should be gone"


def test_both_texts_link_to_where_they_live():
    body = JS[JS.index("function renderMarkerCard"):
              JS.index("async function openMarkerEvidence")]
    assert "selectMarker(marker.id, { scroll: true })" in body, "claim -> manuscript"
    assert "goToCitedPage(q.page)" in body, "quote -> cited paper"


def test_every_score_tier_has_a_colour():
    css = (STATIC / "app.css").read_text()
    for tier in ("good", "fair", "weak", "bad"):
        assert f".score-{tier}" in css


def test_the_library_row_shows_score_times_cited_and_pages():
    body = JS[JS.index("function renderReferences"):
              JS.index("async function updateFromFolder")]
    assert "scoreChip(score)" in body
    assert "r.cited_count" in body and "r.pages" in body


def test_the_library_score_reports_the_best_use():
    """A work can be cited well in one place and loosely in another. The list
    answers "is this reference pulling its weight anywhere"; the panel answers
    it per citation."""
    body = JS[JS.index("function scoreChip"):JS.index("function scoreBadge")]
    assert "high >= 4" in body, "the tier follows the best score"
    assert "String(high)" in body


def test_statuses_are_named_for_what_they_mean():
    """"no-claim" describes the mechanism -- no figure to screen -- and reads
    as a verdict on the citation, which it is not."""
    assert "STATUS_LABEL" in JS
    for internal, shown in (("verified", "figure verified"),
                            ("not-found", "figure missing"),
                            ("no-source", "paper missing"),
                            ("no-claim", "not quantified")):
        assert f'"{internal}"' in JS and shown in JS


def test_header_counts_agree_in_number():
    """"3 figure verified" read as a typo, in the header of every screenshot."""
    body = JS[JS.index("function renderCounts"):JS.index("function renderBackend")]
    for shown in ("figures verified", "figures missing", "papers missing"):
        assert shown in JS
    assert "counts[k] === 1" in body, "one figure is still singular"


def test_scores_do_not_survive_into_a_different_manuscript():
    body = JS[JS.index("async function chooseManuscript"):JS.index("async function goFromSetup")]
    assert "state.scores = {}" in body


def test_scores_are_loaded_even_when_no_new_pass_starts():
    """A manuscript opened a second time has every citation judged already, so
    the pass reports total 0 -- and returning there left the library with no
    scores in exactly the case where they all existed."""
    body = JS[JS.index("async function startAssessing"):
              JS.index("function watchAssessing")]
    assert "await refreshScores()" in body
    assert "if (!begun.total) return" not in body, "the early return was the bug"


def test_the_score_fetch_has_one_implementation():
    """Two copies of it drifted: one populated state.scores and one did not."""
    assert JS.count("/api/assess/summary") == 1


def test_both_panes_have_a_search_box():
    assert 'id="find-manuscript"' in HTML and 'id="find-cited"' in HTML
    assert "async function runFind" in JS


def test_search_hits_do_not_overwrite_evidence_highlights():
    """The passage a citation points at is the answer the reader came for; a
    search must not paint over it."""
    css = (STATIC / "app.css").read_text()
    assert ".find-hit" in css and ".hl" in css
    body = JS[JS.index("function paintFinds"):JS.index("function goToFind")]
    assert '"find-hit"' in body
    assert "querySelectorAll(\".find-hit\")" in body, "only its own marks are cleared"


def test_the_current_hit_is_distinguished():
    css = (STATIC / "app.css").read_text()
    assert ".find-hit.current" in css
    assert "find-hit current" in JS


def test_searching_a_different_paper_starts_over():
    body = JS[JS.index("async function showCited"):JS.index("function renderCited")]
    assert "cited.paperId !== paperId" in body
    assert "finds.cited = { hits: [], at: -1, query: \"\" }" in body


def test_hits_are_repainted_when_pages_are_rebuilt():
    """Pages are lazily rendered, so marks put on a page that has since been
    replaced would simply vanish."""
    assert JS.count("repaintFinds(") >= 3


def test_the_splitter_measures_against_the_layout_row():
    """It used "the reader's parent" to mean <main>. The reader gained a
    wrapper when the search bar arrived, so that stopped being true and the
    divider would not move."""
    body = JS[JS.index("function setSplit"):JS.index("function startRailResize")
              if "startRailResize" in JS else JS.index("function storedSplit")]
    assert 'querySelector("main")' in JS
    assert '$("reader").parentElement' not in JS, (
        "the divider must not measure through the reader's parent"
    )


def test_the_reader_wrapper_is_a_sibling_of_the_splitter():
    """The search bar and the pages scroll together, so they share a wrapper;
    the divider sits beside that wrapper, not inside it."""
    order = [m for m in re.findall(r'id="(reader-pane|splitter|cited|rail)"', HTML)]
    assert order == ["reader-pane", "splitter", "cited", "rail"], order


def test_the_divider_listens_on_the_window_not_on_itself():
    """setPointerCapture depends on the element still being laid out and the
    pointer id still being valid, and when it fails it fails silently -- the
    divider simply never moves, with nothing to see."""
    start = JS.index("function startResize")
    body = JS[start:JS.index("function renderChatTargets", start)]
    assert 'window.addEventListener("pointermove"' in body
    assert ".setPointerCapture(" not in JS, "the call, not the comment"


def test_the_drag_and_the_clamp_divide_by_the_same_total():
    """Two different totals meant the pointer and the pane disagreed."""
    start = JS.index("function startResize")
    body = JS[start:JS.index("function renderChatTargets", start)]
    assert '$("splitter").offsetWidth' in body, "the drag must subtract the divider too"


def test_no_raw_status_name_reaches_the_reader():
    """"no-claim" names the mechanism, not the finding, and reads as a verdict
    on the citation. It leaked through the marker tooltip."""
    # The two survivors build CSS class names, not text a reader sees.
    raw = re.findall(r"\$\{m\.status\}", JS)
    classy = re.findall(r"[mb]-\$\{m\.status\}", JS)
    assert len(raw) == len(classy), "a raw status name is being displayed"
    assert "markerTooltip" in JS
    body = JS[JS.index("function markerTooltip"):JS.index("function recolourMarkers")]
    assert "label_for(m.status)" in body


def test_a_scored_marker_is_coloured_by_its_score():
    """The status only ever said whether a figure was found, which is narrower
    than the question the colour answers for someone scanning the page."""
    assert "function recolourMarkers" in JS
    css = (STATIC / "app.css").read_text()
    for tier in ("good", "fair", "weak", "bad"):
        assert f".marker.s-{tier}" in css


def test_markers_are_recoloured_when_scores_arrive():
    body = JS[JS.index("async function refreshScores"):
              JS.index("async function refreshScores") + 500]
    assert "recolourMarkers()" in body


def test_the_status_is_a_sentence_not_a_badge():
    """"no-claim" and "verified" name the mechanism, and a reader has to have
    been told what they mean. Said in full they need no glossary."""
    card = JS[JS.index("function renderMarkerCard"):
              JS.index("async function openMarkerEvidence")]
    assert "label_for(marker.status)" not in card, "the badge should be gone"
    assert "noteFor(marker" in card  # its other arguments are not this test's business

    body = JS[JS.index("function noteFor"):JS.index("/** Argue for a citation")]
    for phrase in ("that figure was found in the",
                   "appears nowhere in the cited paper",
                   "not in the library",
                   "names no figure"):
        assert phrase in body, f"no wording for {phrase}"


def test_the_note_does_not_repeat_itself():
    """The stock reasons restate the sentence above them word for word."""
    body = JS[JS.index("function noteFor"):JS.index("/** Argue for a citation")]
    assert "restates" in body
    assert "no local PDF" in body and "no quantity to check" in body


def test_the_note_keeps_a_reason_that_adds_something():
    """A joint citation is the case worth reading, and it is not boilerplate."""
    body = JS[JS.index("function noteFor"):JS.index("/** Argue for a citation")]
    assert "!restates" in body


def test_each_citation_site_shows_its_own_score():
    """Pressing a reference lists where it appears; those citations can be
    judged very differently and the list is where that shows."""
    body = JS[JS.index("function openReference"):JS.index("/* ---")
              if False else JS.index("async function assignReferenceFile")
              if "assignReferenceFile" in JS[JS.index("function openReference"):]
              else len(JS)]
    assert "state.markerScores" in JS
    assert "scoreChip({ low: score, high: score, n: 1 })" in JS


def test_the_list_score_cannot_drift_when_text_wraps():
    """A pill baseline-aligned in a flex row drifts as soon as the text beside
    it wraps: it aligns to the first line's baseline in a row twice as tall."""
    css = (STATIC / "app.css").read_text()
    chip = re.search(r"^\.score\.chip \{([^}]*)\}", css, re.M)
    assert chip, ".score.chip rule not found"
    for prop in ("align-self: center", "align-items: center",
                 "justify-content: center"):
        assert prop in chip.group(1), f"the disc needs {prop}"


def test_the_rows_holding_a_score_centre_their_children():
    css = (STATIC / "app.css").read_text()
    for selector in (r"\.sites li", r"#refs li"):
        rule = re.search(rf"^{selector} \{{([^}}]*)\}}", css, re.M)
        assert rule and "align-items: center" in rule.group(1), selector


def test_reassess_button_exists_and_is_wired():
    """The only way to clear the judgement cache used to be restarting the
    server."""
    html = (STATIC / "index.html").read_text()
    js = (STATIC / "app.js").read_text()

    assert 'id="reassess"' in html
    assert '$("reassess").onclick = reassessAll;' in js
    assert "async function reassessAll()" in js


def test_reassess_button_is_revealed_with_the_manuscript():
    """Hidden markup that nothing unhides is a dead button."""
    js = (STATIC / "app.js").read_text()

    assert '$("reassess").hidden = false;' in js
    assert '$("reassess").hidden = true;' in js


def test_library_rows_share_one_column_template():
    """Rows only line up as a table if every one uses the same track sizes."""
    css = (STATIC / "app.css").read_text()

    assert "#refs li {" in css
    assert "grid-template-columns:" in css


def test_library_has_a_header_row():
    js = (STATIC / "app.js").read_text()

    assert 'el("li", "head")' in js
    for column in ("Ref", "Title", "Score", "Cited", "Pages"):
        assert f'"{column}"' in js


def test_an_unavailable_reference_is_greyed_including_its_key():
    """.key.clickable sets the accent colour and outranks the row, so greying
    the row alone left unavailable references looking ready to read."""
    css = (STATIC / "app.css").read_text()

    assert "#refs li.missing .key.clickable {" in css
    assert "#refs li.missing {" in css


def _withheld_label(js: str) -> str:
    """The glyph the disc carries when a score was withheld."""
    body = js[js.index("function noScoreChip("):]
    return re.search(r'el\("strong", null, "([^"]*)"\)', body).group(1)


def test_a_withheld_score_is_labelled_not_left_blank():
    """Claude is told to abstain when the excerpts look like the wrong pages.
    Rendering that as nothing made a deliberate abstention identical to an
    assessment that had not run, and the question came back every time."""
    js = (STATIC / "app.js").read_text()
    css = (STATIC / "app.css").read_text()

    assert "function noScoreChip(" in js
    assert _withheld_label(js), "the withheld score needs a mark of its own"
    assert ".score-nv" in css


def test_every_score_site_handles_a_missing_score():
    """All three places a score appears must show the mark, not a gap."""
    js = (STATIC / "app.js").read_text()

    assert js.count("noScoreChip(") >= 4  # the definition plus three uses


def test_the_withheld_mark_is_one_letter_so_it_centres():
    """Text centres on its advance width, not on its ink. "NV" therefore sat
    half a pixel right of the circle -- V's ink overhangs its advance box --
    and had to shrink to .6rem to fit, leaving it smaller than every digit
    beside it. One letter takes the disc's own type and measures dead centre,
    so no tracking or size rule should come back to prop it up."""
    js = (STATIC / "app.js").read_text()
    css = (STATIC / "app.css").read_text()

    assert len(_withheld_label(js)) == 1, "more than one glyph will not centre"
    assert ".score.chip.score-nv strong {" not in css, "the disc needs no fitting rule"


def test_no_judgement_starts_without_being_asked_for():
    """Assessing on open spent the manuscript's whole budget before the reader
    could see the effort setting, let alone change it, and a run in flight
    cannot be called back."""
    opened = JS[JS.index("async function openManuscript"):
                JS.index("async function startAssessing")]
    assert "startAssessing()" not in opened, "opening a manuscript must not judge"

    # Every mention other than the declaration itself, whether it is called or
    # handed to a listener.
    uses = [line.strip() for line in JS.splitlines()
            if "startAssessing" in line and not line.lstrip().startswith(
                ("async function", "function"))]
    assert len(uses) == 1, f"exactly one thing may start a run: {uses}"
    assert "assess-all" in uses[0], "and it is the button"


def test_the_go_button_says_what_it_will_cost():
    """Nine times the spend between low and high, on the same manuscript."""
    body = JS[JS.index("function paintAssessAll"):JS.index("/** Assess relevance")]
    assert "TOKENS_PER_CITATION" in body
    assert "tokens in total" in body
    assert "cannot be called back" in body


def test_one_citation_can_be_judged_on_its_own():
    """Once the sweep stopped running on open, an unjudged citation asked with
    only_ready, got "pending", found no queue, and returned in silence -- so
    judging one citation meant judging all thirty."""
    body = JS[JS.index("async function runAssess"):JS.index("function renderMarkerCard")]
    assert "offer: true" in body, "a citation with no queue must offer to run"

    card = JS[JS.index("function renderMarkerCard"):JS.index("/** What the mechanical")]
    assert "Judge this citation" in card
    assert "runAssess(marker, null, card)" in card, "and it runs without only_ready"


def test_the_assess_button_is_pressable_whenever_it_is_shown():
    """It was disabled on click and never re-enabled, so after one press it
    showed the right number of remaining citations and refused to start them.
    There is nothing for the disabling to protect: the server ignores a start
    while a run is already going."""
    paint = JS[JS.index("function paintAssessAll"):JS.index("/** Assess relevance")]
    assert "button.disabled = false" in paint

    assert "state.assessing" not in JS, "no flag to get stuck on"


def test_judging_is_not_offered_with_nothing_to_judge_through():
    """Without Claude Code or a key, pressing Assess produced one "could not
    reach Claude" per citation. Everything else on the page works, so the
    page should say that rather than offer a button that cannot succeed."""
    assert "state.backend = Boolean(b.cli || b.api)" in JS

    paint = JS[JS.index("function paintAssessAll"):JS.index("/** Assess relevance")]
    assert "state.backend !== false" in paint, "the bar button is withheld"

    card = JS[JS.index("function renderMarkerCard"):JS.index("/** What the mechanical")]
    assert "Judging needs Claude Code" in card, "and the card explains why"
    assert "Everything else here works without it" in card


def test_nothing_toggled_by_hidden_sets_display_unconditionally():
    """The named-selector version of this test kept missing new offenders --
    .effort shipped visible on the empty page for exactly that reason. This
    one finds them: every id or class the script toggles with `hidden`, held
    against the rules that give it a display."""
    css = (STATIC / "app.css").read_text()

    toggled = set(re.findall(r'\$\("([\w-]+)"\)\.hidden\s*=', JS))
    toggled |= {m for m in re.findall(r'\.getElementById\("([\w-]+)"\)\.hidden', JS)}
    # classes carrying `hidden` in the markup, e.g. <div class="findrow" hidden>
    toggled |= {c for c in re.findall(r'class="([\w-]+)"[^>]*\shidden', HTML)}

    offenders = []
    for name in sorted(toggled):
        for selector in (f"#{name}", f".{name}"):
            block = re.search(rf"^{re.escape(selector)}\s*\{{([^}}]*)\}}", css, re.M)
            if block and re.search(r"^\s*display\s*:", block.group(1), re.M):
                # Adding a `:not([hidden])` rule does not excuse this: the
                # unconditional one still wins over the user-agent rule, so the
                # element is visible either way. The only pass is a more
                # specific rule that hides it -- #cited is hidden by
                # body:not(.cited-open), which makes its `hidden` spare.
                hidden_elsewhere = re.search(
                    r"[^\n,{]+\s" + re.escape(selector) + r"\s*\{[^}]*display:\s*none",
                    css)
                if not hidden_elsewhere:
                    offenders.append(selector)

    assert not offenders, (
        f"these set display outright but are toggled with `hidden`, so they "
        f"can never be hidden: {offenders}"
    )


def test_a_negative_finding_is_only_reported_by_something_that_looked():
    """Every citation said "No passage carries this sentence" on opening a
    manuscript -- the result of a check that had not run. Judging became
    opt-in, so that branch became the default state rather than a rarity."""
    card = JS[JS.index("function renderMarkerCard"):JS.index("/** What the mechanical")]
    claim = card.index("No passage carries this sentence")

    # the branch that makes the claim must be guarded by an assessment existing
    guard = card.rindex("} else if (r) {", 0, claim)
    assert claim - guard < 220, "the negative finding must sit inside `else if (r)`"

    assert "Not looked at yet." in card, "and the unchecked state says so"


def test_keyword_passages_never_read_as_evidence():
    """They are free and unread. The card shows them so a reader has a page to
    start on, and must not let them pass for something that was judged."""
    card = JS[JS.index("function renderMarkerCard"):JS.index("/** What the mechanical")]
    assert "Closest passages by keyword, not a judgement" in card
    assert '"quote passage clickable maybe"' in card, "styled apart from evidence"
    assert ".maybe" in (STATIC / "app.css").read_text()

    # and they are only shown when no judgement exists
    assert "!r && ((state.passages[marker.id] || {}).passages || []).length" in card


def test_the_tour_loads_after_the_script_it_calls_into():
    """tour.js uses $, el and switchTab, and wires its button at load."""
    assert HTML.index('src="/static/app.js"') < HTML.index('src="/static/tour.js"')


def _body_of(name: str) -> str:
    """The text of one top-level function in app.js, up to the next one."""
    start = re.search(rf"^(?:async )?function {name}\(", JS, re.M).start()
    after = re.search(r"^(?:async )?function \w+\(", JS[start + 1:], re.M)
    return JS[start:start + 1 + after.start()] if after else JS[start:]


def test_the_tour_starts_once_the_manuscript_is_on_screen():
    """After the library build, so it never stands over the busy overlay, and
    after the Assess button is painted, so the stops it looks for exist."""
    body = _body_of("openManuscript")
    assert "maybeStartTour()" in body
    assert body.rindex("paintAssessAll()") < body.index("maybeStartTour()")
    assert body.index("await buildLibrary") < body.index("maybeStartTour()")


def test_the_tour_button_waits_for_a_manuscript():
    css = (STATIC / "app.css").read_text()
    assert "body:not(.has-manuscript) #tour-open" in css


def test_the_tour_draws_above_the_busy_overlay_and_below_the_crash_bar():
    css = (STATIC / "app.css").read_text()
    z = lambda selector: int(re.search(
        rf"{re.escape(selector)}\s*\{{[^}}]*z-index:\s*(\d+)", css).group(1))
    assert z("#busy, #setup, #browser") < z(".tour") < z("#crash")


def test_the_tabs_are_named_for_what_they_hold():
    """Library read as every paper Sextant has, when the tab is this
    manuscript's references. Marker was Sextant's own word for the box on the
    page, and the tab shows a reference just as often as a citation. Chat
    promised a conversation, and nothing carries over between questions."""
    labels = re.findall(r'<button data-tab="(\w+)"[^>]*>([^<]+)</button>', HTML)
    assert labels == [("refs", "References"), ("marker", "Details"), ("chat", "Ask")]
