from sextant.refs.http import FakeFetcher
from sextant.refs.linkcheck import CROSSREF, check_entry
from sextant.refs.models import BibEntry


def _crossref(title):
    return {"message": {"title": [title]}}


def test_matching_doi_and_title_is_a_match():
    entry = BibEntry(key="k", entry_type="article", title="Rapid Sediment Transport",
                     doi="10.5555/test.2017.0001")
    fetcher = FakeFetcher(json_by_url={
        CROSSREF + "10.5555/test.2017.0001": _crossref("Rapid Sediment Transport"),
    })

    assert check_entry(entry, fetcher).verdict == "match"


def test_hyphenation_difference_is_still_a_match():
    """The kind of case a naive checker calls a mismatch."""
    entry = BibEntry(key="k", entry_type="article", doi="10.5555/test.2021.0002",
                     title="Multi-Layered Non-Woven Fabrics for Hierarchical Air Filtration")
    fetcher = FakeFetcher(json_by_url={
        CROSSREF + "10.5555/test.2021.0002":
            _crossref("Multilayered Nonwoven Fabrics for Hierarchical Air Filtration"),
    })

    assert check_entry(entry, fetcher).verdict == "match"


def test_a_genuinely_wrong_doi_is_a_mismatch():
    entry = BibEntry(key="k", entry_type="article", title="Rapid Sediment Transport",
                     doi="10.5555/WRONG")
    fetcher = FakeFetcher(json_by_url={
        CROSSREF + "10.5555/WRONG": _crossref("An Entirely Different Paper About Pottery"),
    })

    result = check_entry(entry, fetcher)
    assert result.verdict == "mismatch"
    assert result.claimed and result.actual


def test_entry_without_a_doi_is_reported_not_checked():
    entry = BibEntry(key="k", entry_type="article", title="No DOI Here")
    result = check_entry(entry, FakeFetcher())
    assert result.verdict == "no-doi"


def test_doi_that_crossref_does_not_know_is_unresolved():
    entry = BibEntry(key="k", entry_type="article", title="X", doi="10.9999/nope")
    assert check_entry(entry, FakeFetcher()).verdict == "unresolved"


def test_entry_without_a_title_cannot_be_checked():
    """No claim to compare against — say so rather than guessing."""
    entry = BibEntry(key="k", entry_type="misc", doi="10.1/x")
    fetcher = FakeFetcher(json_by_url={CROSSREF + "10.1/x": _crossref("Something")})
    assert check_entry(entry, fetcher).verdict == "no-title"


def test_doi_is_url_encoded_and_stripped():
    entry = BibEntry(key="k", entry_type="article", title="T",
                     doi="  https://doi.org/10.5555/ABC  ")
    fetcher = FakeFetcher(json_by_url={CROSSREF + "10.5555/ABC": _crossref("T")})

    assert check_entry(entry, fetcher).verdict == "match"


def _checked(bib_title, crossref_title):
    entry = BibEntry(key="k", entry_type="article", title=bib_title, doi="10.1/x")
    fetcher = FakeFetcher(json_by_url={CROSSREF + "10.1/x": _crossref(crossref_title)})
    return check_entry(entry, fetcher).verdict


def test_a_hyphen_crossref_writes_as_a_space_is_still_a_match():
    """Crossref can write as a space a hyphen the .bib writes, and the .bib is
    not wrong for it."""
    assert _checked(
        "Thermal Models for Cross-Laminated Timber Panels in Alpine Housing",
        "Thermal Models for Cross Laminated Timber Panels in Alpine Housing",
    ) == "match"


def test_an_escaped_ampersand_is_still_a_match():
    """LaTeX writes \\&, and Crossref sends the title as HTML."""
    assert _checked("Soil Carbon in Forests \\& Grasslands: A Survey",
                    "Soil Carbon in Forests &amp; Grasslands: A Survey") == "match"


def test_markup_in_a_crossref_title_is_still_a_match():
    """Crossref keeps the publisher's italics, line breaks and all."""
    assert _checked(
        "A 300--450 K 96-Well In-Situ Calorimeter With 0.5 mW Baseline Noise, "
        "2 mK Drift, and ±15° Tilt Tolerance",
        "A 300–450-K 96-Well\n                  <i>In</i>\n                  "
        "-Situ Calorimeter With 0.5-mW Baseline Noise, 2-mK Drift, "
        "and ±15° Tilt Tolerance",
    ) == "match"
