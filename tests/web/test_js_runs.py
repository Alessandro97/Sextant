"""Does the browser code actually parse and run?

It did not. A pair of adjacent string literals with no `+` -- Python's
implicit concatenation, which JavaScript does not have -- made app.js fail to
parse entirely. Every feature on the page was dead, and 486 tests passed,
because they checked balanced brackets and identifier names and never once
asked a JavaScript engine whether the file was valid.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "sextant" / "web" / "static" / "app.js"
HARNESS = Path(__file__).parent / "support" / "load_app.js"
CALL_NOTE = Path(__file__).parent / "support" / "call_note.js"
TOGGLE_FIND = Path(__file__).parent / "support" / "toggle_find.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no node")


def test_the_script_is_valid_javascript():
    result = subprocess.run(
        ["node", "--check", str(APP_JS)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"app.js does not parse:\n{result.stderr}"


def test_the_script_runs_top_to_bottom_against_the_real_page():
    """Parsing is not enough: wiring an event onto an element that is not in
    index.html throws at load and kills everything defined after it."""
    result = subprocess.run(
        ["node", str(HARNESS)], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert "THREW AT LOAD" not in result.stdout, result.stdout
    assert "executed top-to-bottom" in result.stdout, result.stdout + result.stderr


def test_the_note_is_written_before_an_assessment_exists():
    """Running the file is not enough either: a function nobody calls at load
    can still be broken. noteFor read `r`, which lives inside runAssess, so
    every click on a citation threw a ReferenceError and left the panel empty.
    The file parses, and it loads -- only calling it shows the fault."""
    result = subprocess.run(
        ["node", str(CALL_NOTE)], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert "THREW" not in result.stdout, result.stdout + result.stderr

    notes = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())
    # A score that was never asked for is not a withheld one, so say nothing.
    assert "not valued" not in notes["before an assessment"]
    assert "not valued" in notes["assessment with no score"]


def test_putting_the_search_away_clears_the_query():
    """Both find bars used to stand open whether or not anyone was searching.
    Behind a lens they can be put away -- and closing has to drop the query
    with them: highlights left on the page with no box on screen explain
    nothing, and there would be no way to step through them either."""
    result = subprocess.run(
        ["node", str(TOGGLE_FIND)], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert "THREW" not in result.stdout, result.stdout + result.stderr

    facts = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())
    assert facts["opened"] == "hidden=false expanded=true"
    assert facts["closed"] == 'hidden=true expanded=false query=""'


def test_a_figure_the_paper_never_gives_is_named_on_the_card(tmp_path):
    """The server names it beside a found figure. The card drops reasons that
    restate its own sentence, and must not drop this one with them."""
    import pymupdf

    from sextant.manuscript.workspace import build_workspace

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72.0, 100.0), "Latency is 20 ms and throughput is 999 Mbit/s [1].")
    page.insert_link({"kind": pymupdf.LINK_NAMED, "from": pymupdf.Rect(300, 90, 320, 102),
                      "name": "cite.Good"})
    doc.save(tmp_path / "m.pdf")
    doc.close()
    refs = tmp_path / "refs"; refs.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), "The measured latency was 20 ms end to end.")
    doc.save(refs / "Good.pdf")
    doc.close()
    reason = build_workspace(tmp_path / "m.pdf", refs, tmp_path / "p.db").markers[0].reason
    assert "999 Mbit/s" in reason

    result = subprocess.run(["node", str(CALL_NOTE), reason], capture_output=True,
                            text=True, cwd=ROOT, check=False)

    notes = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())
    assert "999 Mbit/s" in notes["with the server's reason"], result.stdout + result.stderr


TOUR = Path(__file__).parent / "support" / "tour_steps.js"


def test_the_tour_points_at_each_part_in_turn():
    result = subprocess.run(["node", str(TOUR)], capture_output=True, text=True,
                            cwd=ROOT, check=False)
    assert "THREW" not in result.stdout, result.stdout + result.stderr
    facts = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())

    assert facts["first"] == "Each box is a citation"
    # Thirteen stops. The effort selector has no box on this page, and nothing
    # is missing from the library, so there is no greyed row to point at.
    assert facts["count"] == "1 / 11"
    assert facts["back on first"] == "no"
    assert facts["focus"] == "Next"
    # Below the element, with the cut-out a little larger than it.
    assert facts["card at"] == "100px 134px"
    assert facts["hole at"] == "94px 94px 52px 28px"

    assert facts["next"] == "References"
    assert facts["tab"] == "refs"
    assert facts["back"] == "Each box is a citation"
    assert "Nothing is judged until you ask" not in facts["titles"]
    assert "A paper no source could reach" not in facts["titles"]
    for stop in ("The references folder", "One row per reference", "Score, Cited, Pages",
                 "Getting the missing papers", "Details", "Ask", "What to ask about"):
        assert stop in facts["titles"].split(" | "), stop
    assert facts["titles"].split(" | ")[-1] == "Where to look, not a verdict"
    assert facts["last button"] == "Finish"
    assert facts["centred"] == "yes"
    assert facts["finish"] == "open=no seen=1 tab=refs"


def test_the_tour_can_be_stepped_and_left_from_the_keyboard():
    result = subprocess.run(["node", str(TOUR)], capture_output=True, text=True,
                            cwd=ROOT, check=False)
    facts = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())

    assert facts["arrow"] == "References"
    assert facts["escape"] == "open=no seen=1 keys=0"
    # The app's own shortcuts do not reach the page underneath: j selected a
    # marker mid-tour, switched the tab under the card and made a request.
    assert facts["j during the tour"] == "stopped"
    # Focus stays in the card, or Enter would press a button behind it.
    assert facts["tab from the last button"] == "first button"
    assert facts["shift-tab from the first button"] == "last button"


def test_the_tour_hands_back_the_tab_it_found():
    result = subprocess.run(["node", str(TOUR)], capture_output=True, text=True,
                            cwd=ROOT, check=False)
    facts = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())

    assert facts["tab after a tour started on Ask"] == "chat"


def test_a_tour_already_seen_waits_to_be_asked_for():
    result = subprocess.run(["node", str(TOUR)], capture_output=True, text=True,
                            cwd=ROOT, check=False)
    facts = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())

    assert facts["seen does not start"] == "no"
    assert facts["replay"] == "Each box is a citation"
    # Replayed from the Chat tab, the Library's parts are still pointed at:
    # each stop's tab is shown before its element is looked for.
    assert facts["replay from another tab"] == "1 / 11"


def test_a_card_with_no_room_either_side_goes_where_there_is_more():
    """Below has 304px and above 272px for a 312px card. Below, held inside
    the window, overlaps the element by a few pixels; pinned to the top edge
    it hid the buttons it was describing."""
    result = subprocess.run(["node", str(TOUR)], capture_output=True, text=True,
                            cwd=ROOT, check=False)
    facts = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())

    assert facts["cramped card top"] == "376px"


def test_the_cut_out_stays_inside_the_window():
    result = subprocess.run(["node", str(TOUR)], capture_output=True, text=True,
                            cwd=ROOT, check=False)
    facts = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())

    # 1262 - 6 on the left; on the right it stops at 1400, not 1406.
    assert facts["hole at the edge"] == "1256px 144px"


SCORE_CHIP = Path(__file__).parent / "support" / "score_chip.js"


def test_n_in_a_list_says_it_may_simply_not_be_judged_yet():
    """In the Library, N stands for every reference without a score -- most of
    them, before anything is judged -- and said only that Claude had declined
    to score, which before any judgement is never true."""
    result = subprocess.run(["node", str(SCORE_CHIP)], capture_output=True,
                            text=True, cwd=ROOT, check=False)
    facts = dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())

    assert "not judged" in facts["in a list"], result.stdout + result.stderr
    assert "wrong pages" in facts["on a judged card"]


LANDING = Path(__file__).parent / "support" / "landing_links.js"


def test_a_landing_page_is_only_ever_a_web_link():
    """They come from OpenAlex and Unpaywall. A javascript: URL in that list
    would run in the viewer's own page when clicked."""
    result = subprocess.run(["node", str(LANDING)], capture_output=True, text=True,
                            cwd=ROOT, check=False)
    assert "THREW" not in result.stdout, result.stdout + result.stderr
    hrefs = [line.split(" :: ", 1)[1] for line in result.stdout.splitlines()
             if line.startswith("href :: ")]

    assert hrefs == ["https://zenodo.org/record/1", "http://hdl.handle.net/2117/1"]


def _tour_facts():
    result = subprocess.run(["node", str(TOUR)], capture_output=True, text=True,
                            cwd=ROOT, check=False)
    assert "THREW" not in result.stdout, result.stdout + result.stderr
    return dict(line.split(" :: ", 1) for line in result.stdout.strip().splitlines())


def test_the_card_stays_inside_the_window_beside_the_right_edge():
    """The Ask tab sits against the right edge; unclamped, the card and its
    buttons ran off the window."""
    assert _tour_facts()["card at the edge"] == "1048px"


def test_the_cut_out_stays_inside_the_window_at_every_edge():
    facts = _tour_facts()
    assert facts["hole at the left edge"] == "0px 144px"
    assert facts["hole at the bottom edge"] == "652px 48px"


def test_left_arrow_on_the_first_stop_stays_put():
    facts = _tour_facts()
    assert facts["left on first"] == "Each box is a citation"
    assert facts["then right"] == "References"


def test_a_replayed_tour_opens_on_the_references_tab():
    assert _tour_facts()["tab at start"] == "refs"


def test_an_element_with_no_height_is_not_pointed_at():
    assert _tour_facts()["flat element count"] == "1 / 11"
