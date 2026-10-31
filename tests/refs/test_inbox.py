import pymupdf

from sextant.refs.inbox import adopt, first_page_text
from sextant.refs.models import Resolution

TITLE = "Seasonal Dynamics of Soil Microbial Communities in Alpine Meadows"


def _pdf(path, lines):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 100.0
    for line in lines:
        page.insert_text((72.0, y), line, fontsize=11)
        y += 18.0
    doc.save(path)
    doc.close()
    return path


def test_matches_a_dropped_pdf_to_a_pending_key_by_title(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _pdf(inbox / "downloaded (1).pdf", [TITLE, "A. Author"])

    pending = [Resolution(key="smith2017", status="no-pdf", title=TITLE)]

    adopted = adopt(inbox, pending)

    assert adopted[0].key == "smith2017"
    assert adopted[0].status == "resolved"
    assert adopted[0].resolver == "inbox"


def test_matches_by_doi_printed_on_the_page(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _pdf(inbox / "x.pdf", ["Some Title Nobody Recorded", "DOI: 10.5555/test.2017.0001"])

    pending = [Resolution(key="smith2017", status="no-pdf",
                          title="Totally different recorded title",
                          doi="10.5555/test.2017.0001")]

    assert adopt(inbox, pending)[0].key == "smith2017"


def test_an_unmatchable_pdf_is_left_alone_not_guessed(tmp_path):
    """Filing a paper under the wrong key would produce a confident verdict
    about the wrong document — the same class of error as a wrong highlight."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    dropped = _pdf(inbox / "mystery.pdf", ["An Unrelated Paper About Compilers"])

    pending = [Resolution(key="k", status="no-pdf", title="Glacier Mass Balance")]

    assert adopt(inbox, pending) == []
    assert dropped.exists()


def test_a_pdf_matching_two_pending_refs_is_reported_not_guessed(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _pdf(inbox / "ambiguous.pdf", ["Coral Reefs Everywhere"])

    pending = [
        Resolution(key="a", status="no-pdf", title="Coral Reefs Everywhere"),
        Resolution(key="b", status="no-pdf", title="Coral Reefs Everywhere"),
    ]

    assert adopt(inbox, pending) == []


def test_a_file_with_no_text_layer_is_skipped_without_raising(tmp_path, blank_pdf):
    import shutil

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copy(blank_pdf, inbox / "scan.pdf")

    assert adopt(inbox, [Resolution(key="k", status="no-pdf", title="X")]) == []


def test_first_page_text_reads_only_the_first_page(tmp_path):
    path = _pdf(tmp_path / "p.pdf", ["Page One Title"])
    assert "Page One Title" in first_page_text(path)


def test_a_3gpp_spec_matches_on_its_number_not_its_title():
    """A manuscript citing TR 21.905 (Release 15) against a download of
    Release 19: the titles differ only in that parenthesis, so containment
    fails both ways while the number matches exactly."""
    from sextant.refs.inbox import _matches
    from sextant.refs.models import Resolution

    cover = ("3GPP TR 21.905 V19.4.0 (2026-06) Technical Report ... "
             "Vocabulary for 3GPP Specifications (Release 19)")
    wanted = Resolution(
        key="21905", status="unresolved",
        title="Vocabulary for 3GPP Specifications (Release 15)")

    assert _matches(cover, wanted)


def test_the_spec_number_is_read_out_of_a_prefixed_key():
    from sextant.refs.inbox import spec_from_key

    assert spec_from_key("3gpp_ts_23501") == "23.501"
    assert spec_from_key("21905") == "21.905"


def test_a_key_with_no_specification_number_yields_none():
    from sextant.refs.inbox import spec_from_key

    assert spec_from_key("smith2019soil") is None
    assert spec_from_key("3gpp_rel_15") is None


def test_two_specification_numbers_in_a_key_are_refused_as_ambiguous():
    from sextant.refs.inbox import spec_from_key

    assert spec_from_key("compare_23501_and_21905") is None


def test_a_different_specification_does_not_match(tmp_path):
    from sextant.refs.inbox import _matches
    from sextant.refs.models import Resolution

    cover = "3GPP TR 21.905 V16.2.0 Vocabulary for 3GPP Specifications"
    assert not _matches(cover, Resolution(key="23501", status="unresolved",
                                          title="Something else entirely"))


def test_a_journal_masthead_is_not_the_title_of_a_book_it_names(tmp_path):
    """A book called "Medieval Trade" must not take a paper whose first page
    carries the journal "Annals of Medieval Trade" across the top."""
    inbox = tmp_path / "inbox"; inbox.mkdir()
    _pdf(inbox / "annals.pdf", ["ANNALS OF MEDIEVAL TRADE, VOL. 5",
                                "Venetian Glass Exports in the Fifteenth Century",
                                "A. Author"])

    pending = [Resolution(key="smith2005", status="no-pdf",
                          title="Medieval Trade")]

    assert adopt(inbox, pending) == []


def test_a_title_mentioned_in_the_abstract_is_not_this_papers_title(tmp_path):
    inbox = tmp_path / "inbox"; inbox.mkdir()
    _pdf(inbox / "x.pdf", ["A Different Paper About Grazing",
                           "Abstract: unlike Seasonal Dynamics of Soil Microbial",
                           "Communities in Alpine Meadows, we study grazing."])

    pending = [Resolution(key="smith2017", status="no-pdf", title=TITLE)]

    assert adopt(inbox, pending) == []


def test_a_title_wrapped_onto_a_second_line_is_still_found(tmp_path):
    inbox = tmp_path / "inbox"; inbox.mkdir()
    _pdf(inbox / "x.pdf", ["JOURNAL OF ALPINE FIELD STUDIES, VOL. 5",
                           "Seasonal Dynamics of Soil Microbial", "Communities in Alpine Meadows",
                           "A. Author"])

    pending = [Resolution(key="smith2017", status="no-pdf", title=TITLE)]

    assert adopt(inbox, pending)[0].key == "smith2017"


def test_a_page_title_with_a_subtitle_the_bib_leaves_off_is_found(tmp_path):
    inbox = tmp_path / "inbox"; inbox.mkdir()
    _pdf(inbox / "x.pdf", ["Urban Heat Islands and Public Health: A Survey", "A. Author"])

    pending = [Resolution(key="uhi", status="no-pdf",
                          title="Urban Heat Islands and Public Health")]

    assert adopt(inbox, pending)[0].key == "uhi"


def test_a_paper_mentioning_a_specification_is_not_that_specification():
    """A paper whose abstract cites "the architecture in TS 23.501" must not
    be filed as 3gpp_ts_23501."""
    from sextant.refs.inbox import _matches

    page = ("A Scheduling Study\nAbstract: building on the architecture in TS 23.501,\n"
            "we propose a scheme.")
    assert not _matches(page, Resolution(key="3gpp_ts_23501", status="unresolved",
                                         title="System architecture; Stage 2"))


def test_a_ts_cover_is_that_specification():
    """Technical specifications as well as reports."""
    from sextant.refs.inbox import _matches

    page = "3GPP TS 23.501 V16.2.0 (2020-06)\nTechnical Specification\nSystem architecture"
    assert _matches(page, Resolution(key="3gpp_ts_23501", status="unresolved", title="x"))
