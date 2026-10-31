"""Citations written as "[12]" in the body text.

The weakest of the three markers: a bracketed number is just text. Only
numbers the reference list defines are accepted, and the list itself is
excluded from the search.
"""

import os
from pathlib import Path

import pymupdf
import pytest

from sextant.manuscript.bracketed import bracketed_markers


def _paper(path, body, refs):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 90.0
    for line in body:
        page.insert_text((60.0, y), line, fontsize=9)
        y += 13.0
    y += 16.0
    page.insert_text((60.0, y), "References", fontsize=9)
    y += 13.0
    for n, entry in enumerate(refs, start=1):
        page.insert_text((60.0, y), f"[{n}] {entry}", fontsize=8)
        y += 12.0
    doc.save(path)
    doc.close()
    return path


REFS = [f"Author {c}. A Paper About Wetlands Number {n}. J. 20{n:02d}."
        for n, c in enumerate("ABCDEFG", start=1)]


def test_bracketed_numbers_become_markers(tmp_path):
    pdf = _paper(tmp_path / "p.pdf", ["Rates reach 3 Mbit/s in trials [1]."], REFS)

    markers = bracketed_markers(pdf, {"1", "2", "3"})

    assert [m.key for m in markers] == ["1"]
    assert "3 Mbit/s" in markers[0].claim


def test_a_number_the_reference_list_does_not_define_is_skipped(tmp_path):
    """"[73]% women" is a placeholder a real proposal had yet to fill in."""
    pdf = _paper(tmp_path / "p.pdf", ["The cohort is [73]% women overall."], REFS)

    assert bracketed_markers(pdf, {"1", "2", "3"}) == []


def test_the_reference_list_is_not_read_as_citations(tmp_path):
    """Its own labels are "[1] [2] [3]" and would otherwise become markers."""
    pdf = _paper(tmp_path / "p.pdf", ["One sentence citing something [2]."], REFS)

    markers = bracketed_markers(pdf, {str(n) for n in range(1, 8)})

    assert [m.key for m in markers] == ["2"], "only the body citation"


def test_a_range_expands(tmp_path):
    pdf = _paper(tmp_path / "p.pdf", ["Several works agree on this [1-3]."], REFS)

    assert [m.key for m in bracketed_markers(pdf, {"1", "2", "3"})] == ["1", "2", "3"]


def test_markers_carry_a_rectangle_to_highlight(tmp_path):
    pdf = _paper(tmp_path / "p.pdf", ["Rates reach 3 Mbit/s in trials [1]."], REFS)

    (marker,) = bracketed_markers(pdf, {"1"})

    assert marker.rect.x1 > marker.rect.x0
    assert marker.rect.y1 > marker.rect.y0


def test_nothing_is_read_without_a_reference_list(tmp_path):
    """With no entries to check against, every bracket is a guess."""
    pdf = _paper(tmp_path / "p.pdf", ["A sentence with [1] in it."], REFS)

    assert bracketed_markers(pdf, set()) == []


#: A real typeset paper with "[n]" citations. Point SEXTANT_TEST_BRACKETED at
#: one to exercise this path -- the synthetic fixtures above cannot reproduce
#: a publisher's reference list, which is where this has gone wrong before.
REAL = os.environ.get("SEXTANT_TEST_BRACKETED", "")


@pytest.mark.skipif(not (REAL and Path(REAL).exists()),
                    reason="set SEXTANT_TEST_BRACKETED to a real paper")
def test_a_real_published_paper():
    """An earlier heading pattern refused to match "References [1]" and so read
    the list's own labels as citations, reporting exactly double. Only a real
    typeset reference list shows that."""
    from sextant.manuscript.bibliography import bracketed_bibliography
    from sextant.manuscript.links import citation_markers

    entries = bracketed_bibliography(Path(REAL))
    markers = citation_markers(Path(REAL))

    assert entries, "no reference list was parsed"
    assert markers, "no citations were found"
    assert {m.key for m in markers} <= set(entries), "a citation with no entry"


def test_a_citation_joins_its_reference_however_the_list_is_labelled():
    """A LaTeX manuscript carries hyperref keys while its printed list is
    numbered, so a library of 32 references showed 32 opaque keys. The printed
    label is the bridge, and the bracket style is the publisher's business."""
    from sextant.manuscript.bibliography import BibEntryFromPdf, entry_for_citation

    entries = {
        "1": BibEntryFromPdf(key="1", label="[1]", raw="Brown T. Grazing pressure.",
                             title="Grazing pressure", doi="10.5555/a"),
        "12": BibEntryFromPdf(key="12", label="[12]", raw="Lopez R, 2022. A survey.",
                              title="A survey", doi=None),
    }

    for label in ("[12]", "12", "12.", "(12)", " 12 ", "¹²".translate(
            str.maketrans("¹²", "12"))):
        found = entry_for_citation("anykey", label, entries)
        assert found is not None and found.key == "12", f"failed on {label!r}"


def test_an_author_year_key_finds_its_entry_without_a_number():
    """Numeric styles are not universal; an author-year key has no label to
    reduce, so the key itself is matched against the entry text."""
    from sextant.manuscript.bibliography import BibEntryFromPdf, entry_for_citation

    entries = {
        "1": BibEntryFromPdf(key="1", label="", raw="Brown T. Grazing pressure. 2020.",
                             title=None, doi=None),
        "2": BibEntryFromPdf(key="2", label="", raw="Lopez R, Kim H. A survey. 2022.",
                             title=None, doi=None),
    }

    found = entry_for_citation("lopez2022survey", "", entries)

    assert found is not None and found.key == "2"


def test_two_papers_by_one_author_in_one_year_are_not_guessed_between():
    """Common, and attaching the wrong one puts a title on a citation that is
    not its own -- the same error as filing a PDF under the wrong key."""
    from sextant.manuscript.bibliography import BibEntryFromPdf, entry_for_citation

    entries = {
        "1": BibEntryFromPdf(key="1", label="", raw="Lopez R. First paper. 2022.",
                             title=None, doi=None),
        "2": BibEntryFromPdf(key="2", label="", raw="Lopez R. Second paper. 2022.",
                             title=None, doi=None),
    }

    assert entry_for_citation("lopez2022something", "", entries) is None


def test_a_title_that_opens_with_a_numeral_is_not_mistaken_for_a_page_range():
    """"19th-Century Grain Ledgers" was skipped by a screen meant to
    reject "2022;29(1):160-8", and the journal name was returned in its place.
    In many bibliographies a numeral-first title is an ordinary case."""
    from sextant.manuscript.bibliography import _vancouver_title

    raw = ("Smith AB, Jones C, Brown T, et al. 19th-Century Grain Ledgers: "
           "Price Records from Two Inland Markets. Review of Market "
           "History. 2022;29(1):160-8. Available from: 10.5555/test.2022.7.")

    assert _vancouver_title(raw) == ("19th-Century Grain Ledgers: "
                                     "Price Records from Two Inland Markets")


def test_a_doi_line_is_not_read_as_a_title():
    """"Available from: 10.5555/..." reads like a sentence and was returned as
    the title of an entry whose real title began with a digit."""
    from sextant.manuscript.bibliography import _vancouver_title

    raw = ("Doe J, Roe R, Lee HH. 12 Months of Soil Respiration in Boreal "
           "Peatlands. Soil Ecol. 2021;35(4):255-61. Available from: "
           "10.5555/test.2021.7.")

    assert _vancouver_title(raw) == "12 Months of Soil Respiration in Boreal Peatlands"


def test_an_institution_standing_where_the_authors_stand_is_not_the_title():
    """Reports are written by bodies, not people, so the first segment is the
    author and the second is the title."""
    from sextant.manuscript.bibliography import _vancouver_title

    raw = ("International Soil Survey Commission. Sampling protocols required for "
           "the survey of upland soils; 2023. Technical Note ISSC S.214-3.")

    assert _vancouver_title(raw) == ("Sampling protocols required for the survey of "
                                     "upland soils")


def test_a_body_named_inside_a_real_title_is_left_alone():
    """The corporate screen applies to the author position only -- otherwise
    any title mentioning an institute would lose its title."""
    from sextant.manuscript.bibliography import _vancouver_title

    raw = "Smith AB, Jones C. A Survey of the Institute Reference Model. J Ecol. 2020;1(2):3."

    assert _vancouver_title(raw) == "A Survey of the Institute Reference Model"


def test_a_title_ending_in_a_question_mark_stops_there():
    """It ran on into the proceedings: "...Who Pays for Restoration? In: 2022
    Joint European Conference on Environmental Economics...", all one title."""
    from sextant.manuscript.bibliography import _vancouver_title

    raw = ("Smith AB, Jones C. Pricing Wetland Loss in River Deltas: Who Pays "
           "for Restoration? In: 2022 Joint European Conference; 2022. p. 178-83.")

    assert _vancouver_title(raw) == "Pricing Wetland Loss in River Deltas: Who Pays for Restoration"


def test_a_reference_list_is_found_however_the_publisher_labels_it(tmp_path):
    """IEEE brackets, Vancouver and Springer use a bare ordinal, some house
    styles parenthesise. Only the run of ascending labels is common to them."""
    import pymupdf
    from sextant.manuscript.bibliography import labelled_bibliography

    entries = [f"Author {c}. A Paper About Wetlands Number {n}. J Ecol. 20{n:02d};1(2):3."
               for n, c in enumerate("ABCDEFG", start=1)]

    for style, fmt in (("bracketed", "[{n}] {e}"), ("ordinal", "{n}. {e}"),
                       ("parenthesised", "({n}) {e}")):
        doc = pymupdf.open()
        page = doc.new_page()
        y = 90.0
        for line in ["Prose citing something.", "More prose here."]:
            page.insert_text((60.0, y), line, fontsize=9); y += 13.0
        y += 16.0
        page.insert_text((60.0, y), "References", fontsize=9); y += 13.0
        for n, entry in enumerate(entries, start=1):
            page.insert_text((60.0, y), fmt.format(n=n, e=entry), fontsize=8); y += 12.0
        path = tmp_path / f"{style}.pdf"
        doc.save(path); doc.close()

        found = labelled_bibliography(path)

        assert len(found) == len(entries), f"{style}: got {len(found)}"
        assert found["3"].title == "A Paper About Wetlands Number 3", style


def test_numbered_prose_before_the_reference_list_is_not_read_as_one(tmp_path):
    """A run of "1." to "6." in the body -- numbered aims, lemmas, steps -- is
    indistinguishable from a Vancouver list to a regex, and a real paper's six
    numbered equations were parsed as its bibliography. The heading is what
    separates them."""
    import pymupdf
    from sextant.manuscript.bibliography import labelled_bibliography

    doc = pymupdf.open()
    page = doc.new_page()
    y = 70.0
    for n in range(1, 7):
        page.insert_text((60.0, y), f"{n}. The system attains a bound of {n} Mbit/s here.",
                         fontsize=9)
        y += 13.0
    y += 16.0
    page.insert_text((60.0, y), "References", fontsize=9); y += 13.0
    for n, c in enumerate("ABCDEFG", start=1):
        page.insert_text((60.0, y), f"{n}. Author {c}. A Real Reference Number {n}. J Ecol. 2020;1(2):3.",
                         fontsize=8)
        y += 12.0
    path = tmp_path / "prose.pdf"
    doc.save(path); doc.close()

    found = labelled_bibliography(path)

    assert len(found) == 7, "the list after the heading, not the prose before it"
    assert "A Real Reference" in (found["1"].title or "")


def _keys(tmp_path, sentence, known=range(1, 8)):
    pdf = _paper(tmp_path / "p.pdf", [sentence], REFS)
    return [m.key for m in bracketed_markers(pdf, {str(n) for n in known})]


def test_a_comma_separates_two_citations_rather_than_spanning_them(tmp_path):
    """[3, 7] read as a range invented citations 4, 5 and 6, each of which
    could then be faulted for a sentence that never cited it."""
    assert _keys(tmp_path, "Both were studied [3, 7].") == ["3", "7"]


def test_a_list_of_three_is_read_whole(tmp_path):
    assert _keys(tmp_path, "Several were studied [1, 2, 5].") == ["1", "2", "5"]


def test_a_list_can_mix_single_numbers_and_ranges(tmp_path):
    assert _keys(tmp_path, "Several were studied [1, 3-5, 7].") == ["1", "3", "4", "5", "7"]


def test_a_range_across_two_brackets_keeps_the_numbers_between(tmp_path):
    """IEEE style writes [2]-[4] for 2, 3 and 4."""
    assert _keys(tmp_path, "Several were studied [2]-[4].") == ["2", "3", "4"]


def test_two_brackets_side_by_side_are_not_a_range(tmp_path):
    assert _keys(tmp_path, "Several were studied [2], [5].") == ["2", "5"]


def test_a_semicolon_separates_two_citations(tmp_path):
    assert _keys(tmp_path, "Both were studied [3; 7].") == ["3", "7"]


def test_a_range_of_forty_is_not_believed(tmp_path):
    assert _keys(tmp_path, "See [1-41].", known=range(1, 60)) == ["1"]


def test_a_dash_before_a_list_is_not_a_range(tmp_path):
    assert _keys(tmp_path, "Several were studied [2]-[4, 6].") == ["2", "4", "6"]


def test_a_bridge_starts_from_the_last_number_of_the_first_bracket(tmp_path):
    assert _keys(tmp_path, "Several were studied [1, 3]-[5].") == ["1", "3", "4", "5"]


def test_a_dash_elsewhere_between_brackets_is_not_a_range(tmp_path):
    assert _keys(tmp_path, "Both [2] and the 3-4 mm layer [5].") == ["2", "5"]
