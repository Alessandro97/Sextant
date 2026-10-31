"""Citations in a Word-style manuscript.

LaTeX with hyperref hands over the marker rectangle and the bibtex key. Word
gives neither, but Vancouver and AMA styles put the citation in a superscript
run, which PyMuPDF flags -- so the geometry is just as exact and only the key
has to be recovered, from a numbered reference list.
"""

import os
from pathlib import Path

import pymupdf
import pytest

from sextant.manuscript.bibliography import numbered_bibliography
from sextant.manuscript.links import citation_markers
from sextant.manuscript.superscript import _numbers, superscript_markers


def _word_style(path, body, marks, refs=()):
    """A page of prose with superscript citation numbers after it."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72.0, 100.0), body, fontsize=11)
    x = 72.0 + pymupdf.get_text_length(body, fontsize=11)
    for mark in marks:
        page.insert_text((x, 96.0), mark, fontsize=7)
        x += pymupdf.get_text_length(mark, fontsize=7) + 1
    y = 200.0
    for n, entry in enumerate(refs, start=1):
        page.insert_text((72.0, y), f"{n}. {entry}", fontsize=9)
        y += 14.0
    doc.save(path)
    doc.close()
    return path


def test_a_superscript_run_expands_into_its_numbers():
    assert _numbers("1,2") == [1, 2]
    assert _numbers("12-14") == [12, 13, 14]
    assert _numbers("5") == [5]


def test_an_absurd_range_is_refused():
    """"1-9999" is a typo or a year range, not ten thousand citations."""
    assert _numbers("1-9999") == []


def test_superscript_numbers_become_markers(tmp_path):
    pdf = _word_style(tmp_path / "w.pdf", "Rates reach 3 Mbit/s in trials.", ["1,2"])

    markers = superscript_markers(pdf)

    assert [m.key for m in markers] == ["1", "2"]
    assert all(m.rect.x1 > m.rect.x0 for m in markers)


def test_the_claim_is_the_prose_the_citation_terminates(tmp_path):
    pdf = _word_style(tmp_path / "w.pdf", "Rates reach 3 Mbit/s in trials.", ["7"])

    (marker,) = superscript_markers(pdf)

    assert "3 Mbit/s" in marker.claim


def test_a_document_with_no_superscripts_yields_nothing(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), "plain prose", fontsize=11)
    doc.save(tmp_path / "plain.pdf")
    doc.close()

    assert superscript_markers(tmp_path / "plain.pdf") == []


def test_citation_markers_falls_back_to_superscripts(tmp_path):
    """The rest of Sextant must not know or care which kind it got."""
    pdf = _word_style(tmp_path / "w.pdf", "The plume spans 50 km here.", ["3"])

    (marker,) = citation_markers(pdf)

    assert marker.key == "3"
    assert "50 km" in marker.claim


def test_a_numbered_reference_list_is_read(tmp_path):
    pdf = _word_style(
        tmp_path / "w.pdf", "Some prose.", ["1"],
        refs=["Smith AB, Jones C. A Study Of Wetlands. J Ecol. 2020;1(2):3-4.",
              "Doe J. Another Paper Entirely. Ann Rev. 2021;5(6):7-8.",
              "Roe R. A Third Contribution. Sci Rep. 2022;9:10-11.",
              "Poe P. Fourth And Final. Nature. 2023;1:2-3.",
              "Moe M. Fifth For Length. Cell. 2024;4:5-6."])

    entries = numbered_bibliography(pdf)

    assert len(entries) == 5
    assert entries["1"].title == "A Study Of Wetlands"


def test_a_short_numbered_list_is_not_mistaken_for_a_bibliography(tmp_path):
    """Enumerated aims look exactly like reference labels."""
    pdf = _word_style(tmp_path / "w.pdf", "Some prose.", ["1"],
                      refs=["Aim one here.", "Aim two here."])

    assert numbered_bibliography(pdf) == {}


#: A real Word-produced document with superscript citations and a Vancouver
#: reference list. Point SEXTANT_TEST_SUPERSCRIPT at one; the fixtures above
#: only approximate what Word actually emits.
REAL_SUPERSCRIPT = os.environ.get("SEXTANT_TEST_SUPERSCRIPT", "")


@pytest.mark.skipif(
    not (REAL_SUPERSCRIPT and Path(REAL_SUPERSCRIPT).exists()),
    reason="set SEXTANT_TEST_SUPERSCRIPT to a real Word document",
)
def test_a_real_word_document():
    """Every citation resolves to an entry, and every entry that is not an
    unfilled placeholder yields a title. Real proposals carry both."""
    pdf = Path(REAL_SUPERSCRIPT)
    markers = citation_markers(pdf)
    entries = numbered_bibliography(pdf)

    assert markers, "no superscript citations were found"
    assert entries, "no reference list was parsed"
    assert {m.key for m in markers} <= set(entries), "a citation with no entry"
    assert all(e.title for e in entries.values() if not e.raw.startswith("[")), \
        "an entry that is not a placeholder had no title"


def test_the_title_is_found_even_when_authors_end_with_an_initial():
    """"Jones C. A Study Of Wetlands." -- a split that ignores stops after
    capitals keeps authors and title together and returns the journal."""
    from sextant.manuscript.bibliography import _vancouver_title

    assert _vancouver_title(
        "Smith AB, Jones C. A Study Of Wetlands. J Ecol. 2020;1(2):3-4."
    ) == "A Study Of Wetlands"


def test_an_abbreviated_journal_is_not_mistaken_for_a_title():
    from sextant.manuscript.bibliography import _vancouver_title

    assert _vancouver_title(
        "Smith AB, Doe J. Sensitivity analysis in small cohort "
        "studies: a worked example. Ann Intern Med. 2017;12(4):210-216."
    ).startswith("Sensitivity analysis")


def test_a_superscript_the_reference_list_does_not_define_is_skipped(tmp_path):
    pdf = _word_style(tmp_path / "w.pdf", "Rates reach 3 Mbit/s in trials.", ["1,7"])

    assert [m.key for m in superscript_markers(pdf, known={"1", "2"})] == ["1"]


def test_without_a_reference_list_every_superscript_number_still_counts(tmp_path):
    pdf = _word_style(tmp_path / "w.pdf", "Rates reach 3 Mbit/s in trials.", ["1,7"])

    assert [m.key for m in superscript_markers(pdf, known=set())] == ["1", "7"]


def test_one_exponent_does_not_hide_the_bracketed_citations(tmp_path):
    """Superscripts were tried first and any at all were taken: the 2 of km²
    stood in for every citation on the page, and the sentence it sat in was
    then checked against a reference it never cited."""
    doc = pymupdf.open()
    page = doc.new_page()
    body = "The burned area is 500 km"
    page.insert_text((72.0, 100.0), body, fontsize=11)
    x = 72.0 + pymupdf.get_text_length(body, fontsize=11)
    page.insert_text((x, 96.0), "2", fontsize=7)
    page.insert_text((x + 5.0, 100.0), " per region.", fontsize=11)
    y = 124.0
    for n in range(1, 6):
        page.insert_text((72.0, y), f"Result number {n} was reported [{n}].", fontsize=11)
        y += 18.0
    page.insert_text((72.0, y + 20.0), "References", fontsize=11)
    y += 40.0
    for n in range(1, 6):
        page.insert_text((72.0, y), f"[{n}] Author {n}. A Paper About Glaciers {n}. J. 2020.",
                         fontsize=9)
        y += 14.0
    doc.save(tmp_path / "b.pdf")
    doc.close()

    keys = [m.key for m in citation_markers(tmp_path / "b.pdf")]

    assert keys == ["1", "2", "3", "4", "5"]


def test_an_exponent_in_a_superscript_manuscript_is_not_a_citation(tmp_path):
    """Vancouver style, five references, and a 30 m⁹ typo-turned-exponent: the
    9 is a superscript digit like any citation, and the list has no entry 9."""
    doc = pymupdf.open()
    page = doc.new_page()
    body = "The plume spans 50 km here."
    page.insert_text((72.0, 100.0), body, fontsize=11)
    page.insert_text((72.0 + pymupdf.get_text_length(body, fontsize=11), 96.0), "1", fontsize=7)
    body2 = "The pond is 30 m"
    page.insert_text((72.0, 130.0), body2, fontsize=11)
    page.insert_text((72.0 + pymupdf.get_text_length(body2, fontsize=11), 126.0), "9", fontsize=7)
    y = 200.0
    for n, entry in enumerate(["Smith AB. A Study Of Wetlands. J Ecol. 2020;1(2):3-4.",
                               "Doe J. Another Paper Entirely. Ann Rev. 2021;5(6):7-8.",
                               "Roe R. A Third Contribution. Sci Rep. 2022;9:10-11.",
                               "Poe P. Fourth And Final. Nature. 2023;1:2-3.",
                               "Moe M. Fifth For Length. Cell. 2024;4:5-6."], start=1):
        page.insert_text((72.0, y), f"{n}. {entry}", fontsize=9)
        y += 14.0
    doc.save(tmp_path / "w.pdf")
    doc.close()

    assert [m.key for m in citation_markers(tmp_path / "w.pdf")] == ["1"]
