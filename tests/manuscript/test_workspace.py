import pymupdf

from sextant.manuscript.workspace import build_workspace
from sextant.store.db import Store


def _manuscript(path, entries):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 100.0
    for marker, key, claim in entries:
        page.insert_text((72.0, y), f"{claim} {marker}.", fontsize=11)
        width = pymupdf.get_text_length(f"{claim} ", fontsize=11)
        mwidth = pymupdf.get_text_length(marker, fontsize=11)
        page.insert_link({"kind": pymupdf.LINK_NAMED,
                          "from": pymupdf.Rect(72.0 + width, y - 9.0,
                                               72.0 + width + mwidth, y + 2.0),
                          "name": f"cite.{key}"})
        y += 24.0
    doc.save(path)
    doc.close()
    return path


def _cited(path, body):
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), body, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_a_marker_whose_quantity_is_in_the_source_is_verified(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Good.pdf", "Peak throughput was 3 Mbit/s overall.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.markers[0].status == "verified"
    assert ws.markers[0].span.page == 1


def test_a_marker_whose_quantity_is_absent_is_flagged(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Bad", "Rates reach 99 GHz")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Bad.pdf", "This paper is about medieval trade routes.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.markers[0].status == "not-found"


def test_a_marker_with_no_local_paper_is_marked_missing(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Gone", "Rates reach 3 Mbit/s")])

    ws = build_workspace(pdf, tmp_path / "refs", db_path=tmp_path / "p.db")

    assert ws.markers[0].status == "no-source"


def test_a_marker_with_no_quantity_is_unchecked_not_failed(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Vague", "Many schemes exist")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Vague.pdf", "Assorted schemes.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.markers[0].status == "no-claim"


def test_the_library_is_scoped_to_this_manuscript(tmp_path, sample_pdf):
    """A paper in the store this manuscript does not cite must not appear.
    That is the whole point of scoping."""
    store = Store.open(tmp_path / "p.db")
    store.add_paper(sample_pdf, title="Unrelated Paper")
    store.close()

    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Good.pdf", "Peak was 3 Mbit/s.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert [r.key for r in ws.references] == ["Good"]


def test_a_reference_cited_twice_appears_once_in_the_library(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[1]", "Good", "Rates reach 3 Mbit/s"),
        ("[1]", "Good", "The plume spans 50 km"),
    ])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Good.pdf", "Peak was 3 Mbit/s over 50 km.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert len(ws.references) == 1
    assert ws.references[0].cited_count == 2


def test_a_missing_reference_is_reported_as_needing_a_fetch(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Gone", "Rates reach 3 Mbit/s")])

    ws = build_workspace(pdf, tmp_path / "refs", db_path=tmp_path / "p.db")

    assert ws.references[0].available is False
    assert ws.references[0].paper_id is None


def test_references_are_ordered_by_marker_number(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[2]", "Second", "The plume spans 50 km"),
        ("[1]", "First", "Rates reach 3 Mbit/s"),
    ])

    ws = build_workspace(pdf, tmp_path / "refs", db_path=tmp_path / "p.db")

    assert [r.marker for r in ws.references] == ["[1]", "[2]"]


def test_counts_summarise_the_manuscript(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[1]", "Good", "Rates reach 3 Mbit/s"),
        ("[2]", "Gone", "The plume spans 50 km"),
    ])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Good.pdf", "Peak was 3 Mbit/s.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.counts() == {"verified": 1, "no-source": 1}


def test_page_sizes_are_reported_for_the_overlay(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])

    ws = build_workspace(pdf, tmp_path / "refs", db_path=tmp_path / "p.db")

    assert len(ws.page_sizes) == ws.pages
    assert ws.page_sizes[0][0] > 0


def _joint(path):
    """One sentence citing two papers: '... 3 Mbit/s [1], [2].'"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72.0, 100.0), "Rates reach 3 Mbit/s [1], [2].", fontsize=11)
    x1 = 72.0 + pymupdf.get_text_length("Rates reach 3 Mbit/s ", fontsize=11)
    x2 = 72.0 + pymupdf.get_text_length("Rates reach 3 Mbit/s [1], ", fontsize=11)
    for x, key in ((x1, "HasIt"), (x2, "Alongside")):
        page.insert_link({"kind": pymupdf.LINK_NAMED,
                          "from": pymupdf.Rect(x, 91.0, x + 14.0, 102.0),
                          "name": f"cite.{key}"})
    doc.save(path)
    doc.close()
    return path


def test_a_jointly_cited_paper_is_not_faulted_for_the_whole_sentence(tmp_path):
    """"... 5 ms ... [24], [25]" cites two papers for one statement. Faulting
    [25] for a quantity [24] carries is an accusation the manuscript does not
    deserve."""
    pdf = _joint(tmp_path / "m.pdf")
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "HasIt.pdf", "Peak throughput was 3 Mbit/s overall.")
    _cited(refs / "Alongside.pdf", "A companion paper about medieval trade routes.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")
    by_key = {m.key: m for m in ws.markers}

    assert by_key["HasIt"].status == "verified"
    assert by_key["Alongside"].status != "not-found"
    assert "HasIt" in by_key["Alongside"].reason


def test_a_lone_citation_missing_its_quantity_is_still_flagged(tmp_path):
    """The joint-citation rule must not silence a genuine finding."""
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Alone", "Rates reach 99 GHz")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Alone.pdf", "This paper is about medieval trade routes.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.markers[0].status == "not-found"


def test_no_fault_when_a_jointly_cited_paper_could_not_be_checked(tmp_path):
    """The paper carrying the number may be the one with no local copy."""
    pdf = _joint(tmp_path / "m.pdf")
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Alongside.pdf", "A companion paper about medieval trade routes.")
    # HasIt.pdf deliberately absent.

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")
    by_key = {m.key: m for m in ws.markers}

    assert by_key["HasIt"].status == "no-source"
    assert by_key["Alongside"].status == "no-claim"
    assert "not available" in by_key["Alongside"].reason


def _two_sentences(path):
    """A quantity in the first sentence, the citation terminating the second."""
    doc = pymupdf.open()
    page = doc.new_page()
    text = ("The sensor drift is 1.1 dB/K in the cold room. "
            "These values apply to the reference unit only")
    page.insert_text((72.0, 100.0), f"{text} [1]", fontsize=9)
    x = 72.0 + pymupdf.get_text_length(f"{text} ", fontsize=9)
    page.insert_link({"kind": pymupdf.LINK_NAMED,
                      "from": pymupdf.Rect(x, 92.0, x + 12.0, 102.0),
                      "name": "cite.Spec"})
    doc.save(path)
    doc.close()
    return path


def test_a_quantity_in_a_neighbouring_sentence_can_still_verify(tmp_path):
    """Credit generously: the citation plausibly covers the parameter set."""
    pdf = _two_sentences(tmp_path / "m.pdf")
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Spec.pdf", "Sensor drift 1.1 dB/K in the cold-room table.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.markers[0].status == "verified"


def test_but_it_cannot_be_faulted_for_one(tmp_path):
    """Blame strictly: a citation is only unsupported when the sentence it
    actually terminates names something the cited paper lacks. Sextant faulted
    a cited standard for '49.3 kW', a value the manuscript computed one
    sentence earlier."""
    pdf = _two_sentences(tmp_path / "m.pdf")
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Spec.pdf", "This paper is about medieval trade routes.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.markers[0].status == "no-claim"
    assert "another sentence" in ws.markers[0].reason


def test_a_quantity_in_its_own_sentence_is_still_faulted(tmp_path):
    """The generosity must not silence a genuine finding."""
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Alone", "Rates reach 99 GHz")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Alone.pdf", "This paper is about medieval trade routes.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.markers[0].status == "not-found"


def test_a_reference_carries_the_citation_text_the_manuscript_prints(
        tmp_path, latex_like_manuscript):
    """Without this the library showed 32 opaque keys -- 4821377, and nothing
    to search with. The printed label joins the two."""
    from sextant.manuscript.workspace import build_workspace

    pdf = latex_like_manuscript(tmp_path / "m.pdf")
    refs = tmp_path / "refs"; refs.mkdir()

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.references, "no references were scoped"
    with_text = [r for r in ws.references if r.raw]
    assert len(with_text) == len(ws.references), (
        f"only {len(with_text)} of {len(ws.references)} carry citation text"
    )
    assert all(r.doi for r in ws.references), "the DOI in the text was not picked up"
    assert any(r.key == "lopez2022survey" for r in ws.references), (
        "a non-numeric key must join too"
    )


def test_a_key_that_is_not_a_plain_filename_still_finds_its_paper(tmp_path):
    """DBLP keys carry a slash. The paper is filed under a safe name, and
    reading it back has to use the same one."""
    from sextant.refs.folder import key_pdf

    key = "DBLP:journals/corr/abs-2005-14165"
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", key, "Rates reach 3 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(key_pdf(refs, key), "Peak throughput was 3 Mbit/s overall.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.markers[0].key == key
    assert ws.markers[0].status == "verified"


def test_a_figure_missing_beside_a_found_one_is_still_reported(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[1]", "Good", "Latency is 20 ms and throughput is 999 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Good.pdf", "The measured latency was 20 ms end to end.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert ws.markers[0].status == "verified"
    assert "999 Mbit/s" in ws.markers[0].reason


def test_a_paper_put_in_refs_by_hand_can_be_opened_and_judged(tmp_path):
    """Found in a real-browser run: refs/<key>.pdf placed by hand -- or a
    reader's own copy, which fetch now leaves where it is -- was reported
    available and checked, but had no store entry, so its citation could not be
    opened beside the manuscript or judged, and Update from folder skipped it
    as not missing."""
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Good.pdf", "Peak throughput was 3 Mbit/s overall.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    (good,) = ws.references
    assert good.available
    assert good.paper_id is not None
    store = Store.open(tmp_path / "p.db")
    try:
        assert store.get_paper(good.paper_id) is not None
    finally:
        store.close()


def test_adopting_a_hand_placed_paper_leaves_the_file_alone(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    theirs = _cited(refs / "Good.pdf", "Peak throughput was 3 Mbit/s overall.")
    before = theirs.read_bytes()

    build_workspace(pdf, refs, db_path=tmp_path / "p.db")
    build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert not theirs.is_symlink()
    assert theirs.read_bytes() == before
    store = Store.open(tmp_path / "p.db")
    try:
        assert len(store.list_papers()) == 1, "adopted once, not once per open"
    finally:
        store.close()


def test_a_joint_citation_in_the_viewer_is_not_told_its_partners_figure_is_missing(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[1]", "A", "Latency is 20 ms and capacity is 5 Gbps"),
    ])
    # Both markers on one sentence: append a second marker to the same line.
    doc = pymupdf.open(pdf)
    page = doc[0]
    claim = "Latency is 20 ms and capacity is 5 Gbps [1]"
    x = 72.0 + pymupdf.get_text_length(claim + " ", fontsize=11)
    page.insert_text((x, 100.0), "[2]", fontsize=11)
    page.insert_link({"kind": pymupdf.LINK_NAMED, "name": "cite.B",
                      "from": pymupdf.Rect(x, 91.0, x + 14.0, 102.0)})
    doc.saveIncr()
    doc.close()
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "A.pdf", "Measured latency of 20 ms.")
    _cited(refs / "B.pdf", "A capacity of 5 Gbps.")

    ws = build_workspace(pdf, refs, db_path=tmp_path / "p.db")

    assert {m.key: m.status for m in ws.markers} == {"A": "verified", "B": "verified"}
    assert all(m.reason == "" for m in ws.markers), [m.reason for m in ws.markers]
