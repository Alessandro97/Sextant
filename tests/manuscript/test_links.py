import pymupdf
import pytest

from sextant.manuscript.links import (
    MAX_SENTENCE,
    NoCitationLinksError,
    citation_markers,
    sentence_at,
)
from sextant.models import Page


def _manuscript(path, entries):
    """A PDF with real hyperref-style citation links.

    entries: [(marker_text, key, claim_prefix)]
    """
    doc = pymupdf.open()
    page = doc.new_page()
    y = 100.0
    for marker, key, claim in entries:
        page.insert_text((72.0, y), f"{claim} {marker}.", fontsize=11)
        width = pymupdf.get_text_length(f"{claim} ", fontsize=11)
        mwidth = pymupdf.get_text_length(marker, fontsize=11)
        rect = pymupdf.Rect(72.0 + width, y - 9.0, 72.0 + width + mwidth, y + 2.0)
        page.insert_link({"kind": pymupdf.LINK_NAMED, "from": rect, "name": f"cite.{key}"})
        y += 24.0
    doc.save(path)
    doc.close()
    return path


def test_reads_the_key_and_marker_of_each_citation(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[1]", "Smith20", "Rates reach 3 Mbit/s"),
        ("[2]", "Jones21", "The plume spans 50 km"),
    ])

    markers = citation_markers(pdf)

    assert [(m.marker, m.key) for m in markers] == [("[1]", "Smith20"), ("[2]", "Jones21")]


def test_each_marker_carries_its_page_and_rectangle(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Smith20", "Rates reach 3 Mbit/s")])

    (marker,) = citation_markers(pdf)

    assert marker.page == 1
    assert marker.rect.x1 > marker.rect.x0
    assert marker.rect.y1 > marker.rect.y0


def test_the_claim_is_the_text_running_up_to_the_marker(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Smith20", "Rates reach 3 Mbit/s")])

    (marker,) = citation_markers(pdf)

    assert "3 Mbit/s" in marker.claim
    assert "Rates reach" in marker.claim


def test_a_claim_does_not_bleed_in_from_the_previous_citation(tmp_path):
    """Each marker's claim must stop at the marker before it, or every claim
    on a page accumulates every quantity on that page."""
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[1]", "Smith20", "Rates reach 3 Mbit/s"),
        ("[2]", "Jones21", "The plume spans 50 km"),
    ])

    first, second = citation_markers(pdf)

    assert "3 Mbit/s" in first.claim
    assert "3 Mbit/s" not in second.claim
    assert "50 km" in second.claim


def test_a_pdf_with_no_citation_links_is_rejected_clearly(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), "no citations here", fontsize=11)
    doc.save(tmp_path / "plain.pdf")
    doc.close()

    with pytest.raises(NoCitationLinksError):
        citation_markers(tmp_path / "plain.pdf")


def test_the_real_manuscript_yields_the_measured_marker_count(real_manuscript_pdf):
    """Measured 2026-10-30: its 29 \\cite commands name 37 keys, and the
    compiled PDF carries 37 citation links. An earlier 45 matched neither."""
    markers = citation_markers(real_manuscript_pdf)

    assert len(markers) == 37
    assert all(m.key for m in markers)
    assert all(m.marker.startswith("[") for m in markers)


def test_real_manuscript_claims_carry_the_quantities_they_cite(real_manuscript_pdf):
    """The whole point of taking claims from the PDF: they arrive de-TeXed."""
    from sextant.audit.quantities import quantities

    markers = citation_markers(real_manuscript_pdf)
    with_quantity = [m for m in markers if quantities(m.claim)]

    assert len(with_quantity) >= 8


def test_a_claim_does_not_open_with_the_previous_marker(tmp_path):
    """The floor between claims sits past the marker word, not at its start,
    or every claim after the first on a page begins with the previous [N]."""
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[1]", "First", "Rates reach 3 Mbit/s"),
        ("[2]", "Second", "The plume spans 50 km"),
    ])

    _, second = citation_markers(pdf)

    assert not second.claim.startswith("[1]")
    assert second.claim == "The plume spans 50 km."


def test_a_claim_stops_at_the_sentence_it_terminates(tmp_path):
    """A 220-char window ending at "[1]" swept in "49.3 kW." from the
    previous sentence -- a value the manuscript computed itself -- and the
    cited paper was faulted for not containing it."""
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[1]", "Model", "The peak load is 49.3 kW. The demand follows a seasonal law"),
    ])

    (marker,) = citation_markers(pdf)

    assert "49.3" not in marker.claim
    assert "seasonal law" in marker.claim


def test_a_single_sentence_claim_is_left_whole(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf",
                      [("[1]", "K", "Field trials report only 3 Mbit/s per node")])

    (marker,) = citation_markers(pdf)

    assert "3 Mbit/s" in marker.claim


def test_the_claim_is_the_sentence_the_marker_sits_in(tmp_path):
    """Not the one before it. A citation in a short sentence gets that short
    sentence; the preceding one is context, not claim."""
    pdf = _manuscript(tmp_path / "m.pdf",
                      [("[1]", "K", "Rates reach 3 Mbit/s in trials. Also")])

    (marker,) = citation_markers(pdf)

    assert marker.claim == "Also."
    assert "3 Mbit/s" in marker.context, "the sentence before is still context"


def test_a_marker_mid_sentence_still_gets_the_whole_sentence(tmp_path):
    """"Under these conditions [4], the sensors track each animal..." yielded
    only the clause before the marker: a subordinate opening that asserts
    nothing and retrieves nothing."""
    doc = pymupdf.open()
    page = doc.new_page()
    text = "Under these conditions [1], the sensors follow each animal as it moves."
    page.insert_text((60.0, 100.0), text, fontsize=9)
    x = 60.0 + pymupdf.get_text_length("Under these conditions ", fontsize=9)
    page.insert_link({"kind": pymupdf.LINK_NAMED,
                      "from": pymupdf.Rect(x, 92.0, x + 12.0, 102.0),
                      "name": "cite.K"})
    doc.save(tmp_path / "m.pdf")
    doc.close()

    (marker,) = citation_markers(tmp_path / "m.pdf")

    assert marker.claim.startswith("Under these conditions")
    assert "sensors follow each animal as it moves" in marker.claim


def test_the_marker_itself_is_not_part_of_the_claim(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "K", "Rates reach 3 Mbit/s")])

    (marker,) = citation_markers(pdf)

    assert "[1]" not in marker.claim


def test_markers_in_one_sentence_share_a_group(tmp_path):
    """They cite that sentence jointly, so none may be faulted alone."""
    doc = pymupdf.open()
    page = doc.new_page()
    text = "Rates reach 3 Mbit/s [1], [2] in trials."
    page.insert_text((60.0, 100.0), text, fontsize=9)
    for offset, key in ((("Rates reach 3 Mbit/s "), "A"), (("Rates reach 3 Mbit/s [1], "), "B")):
        x = 60.0 + pymupdf.get_text_length(offset, fontsize=9)
        page.insert_link({"kind": pymupdf.LINK_NAMED,
                          "from": pymupdf.Rect(x, 92.0, x + 11.0, 102.0),
                          "name": f"cite.{key}"})
    doc.save(tmp_path / "m.pdf")
    doc.close()

    markers = citation_markers(tmp_path / "m.pdf")

    assert len({m.group for m in markers}) == 1
    assert all("3 Mbit/s" in m.claim for m in markers)


def test_numbered_equation_ends_the_sentence_before_the_next():
    """A display equation carries no full stop, so its tag is the only mark of
    where it ends. Without treating it as a boundary, the prose before an
    equation fused to the prose after it and the citation was judged against a
    sentence it was never offered for."""
    page = Page(
        number=4,
        text=(
            "The queuing delay adds the wait in the input buffer to the wait "
            "at the output port: Tq = W Q + L R , (14) "
            "Finally, Tc covers the time spent checking each packet "
            "at the server [21]."
        ),
        words=(),
    )
    claim, _ = sentence_at(page, page.text.index("checking"))

    assert claim.startswith("Finally, Tc covers")
    assert "queuing delay" not in claim


def test_equation_tag_followed_by_lowercase_continues_the_sentence():
    """"(9) where alpha = 0.8 is..." is one sentence running through its own
    equation, not two. Only a capital marks a genuinely new sentence, which is
    what separates an equation's tag from a reference to one."""
    page = Page(
        number=3,
        text=(
            "We obtain the growth rate as follows: GR = min(x), (9) "
            "where alpha is the efficiency factor of the bound [19]."
        ),
        words=(),
    )
    claim, _ = sentence_at(page, page.text.index("efficiency factor"))

    assert claim.startswith("We obtain the growth rate")
    assert "where alpha" in claim


def test_inline_equation_reference_is_not_a_boundary():
    """"computed following Eqs. (1) and (2) respectively" must stay whole."""
    page = Page(
        number=2,
        text="The paths are computed following Eqs. (1) and (2) respectively [7].",
        words=(),
    )
    claim, _ = sentence_at(page, page.text.index("respectively"))

    assert "Eqs" in claim and "respectively" in claim


def test_et_al_does_not_end_a_sentence():
    page = Page(
        number=1,
        text="The measurements of Brown et al. cover the whole basin [3].",
        words=(),
    )
    claim, _ = sentence_at(page, page.text.index("whole basin"))

    assert claim.startswith("The measurements")


def test_overlong_sentence_is_cut_at_a_word_boundary():
    """A page with no punctuation must not hand back half a word. The clamp
    landed mid-token and produced "uency, the ratio over interval B is"."""
    text = "frequency " * 120
    page = Page(number=1, text=text, words=())

    claim, start = sentence_at(page, len(text) // 2)

    assert len(claim) <= MAX_SENTENCE
    assert not claim.startswith("uency")
    assert claim.split()[0] == "frequency"
