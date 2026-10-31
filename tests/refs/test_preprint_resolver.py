"""A published article's preprint, found through Crossref's has-preprint
relation and fetched only after every published copy has failed."""

import pymupdf

from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry
from sextant.refs.resolvers.crossref import crossref_work_url
from sextant.refs.resolvers.openalex import work_url
from sextant.refs.resolvers.preprint import PreprintResolver

DOI = "10.5555/test.2021.0004"
TITLE = "Antibody Persistence after Seasonal Influenza Vaccination in Rural Clinics"
ENTRY = BibEntry(key="k", entry_type="article", title=TITLE, doi=DOI)


def _pdf(title):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(["medRxiv preprint", title, "A. Author"]):
        page.insert_text((72, 80 + 14 * i), line, fontsize=10)
    return doc.tobytes()


def _record(*preprints):
    return {"message": {"DOI": DOI, "title": [TITLE], "relation": {
        "has-preprint": [{"id-type": "doi", "id": p, "asserted-by": "object"}
                         for p in preprints]}}}


def test_a_medrxiv_preprint_is_fetched_and_called_a_preprint(tmp_path):
    pre = "10.5555/medrxiv.2021.0001"
    url = "https://www.medrxiv.org/content/x.full.pdf"
    fetcher = FakeFetcher(
        json_by_url={crossref_work_url(DOI): _record(pre),
                     work_url(pre): {"id": "W2", "title": TITLE, "locations": [
                         {"pdf_url": url, "version": "acceptedVersion",
                          "source": {"display_name": "medRxiv"}}]}},
        bytes_by_url={url: _pdf(TITLE)})

    result = PreprintResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "resolved", result.reason
    assert "preprint from medRxiv" in result.reason


def test_an_arxiv_preprint_is_fetched_from_arxiv(tmp_path):
    fetcher = FakeFetcher(
        json_by_url={crossref_work_url(DOI): _record("10.48550/arXiv.2501.00001")},
        bytes_by_url={"https://arxiv.org/pdf/2501.00001": _pdf(TITLE)})

    result = PreprintResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "resolved"
    assert "arXiv" in result.reason


def test_a_preprint_titled_differently_is_not_filed(tmp_path):
    """Preprints are often retitled on publication; without the title on its
    page, nothing confirms it is the cited work."""
    fetcher = FakeFetcher(
        json_by_url={crossref_work_url(DOI): _record("10.48550/arXiv.2501.00001")},
        bytes_by_url={"https://arxiv.org/pdf/2501.00001": _pdf("An Earlier Working Title")})

    assert PreprintResolver().resolve(ENTRY, fetcher, tmp_path).status != "resolved"


def test_an_article_with_no_preprint_costs_nothing_new(tmp_path):
    fetcher = FakeFetcher(json_by_url={crossref_work_url(DOI): {"message": {"DOI": DOI}}})

    result = PreprintResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "unresolved"
    assert set(fetcher.calls) == {crossref_work_url(DOI), work_url(DOI)}, "both already cached"


def test_the_preprint_step_takes_the_preprints_openalex_listed(tmp_path):
    url = "https://www.biorxiv.org/x.full.pdf"
    fetcher = FakeFetcher(
        json_by_url={crossref_work_url(DOI): {"message": {"DOI": DOI}},
                     work_url(DOI): {"id": "W1", "title": TITLE, "locations": [
                         {"pdf_url": url, "version": "submittedVersion",
                          "source": {"display_name": "bioRxiv"}}]}},
        bytes_by_url={url: _pdf(TITLE)})

    result = PreprintResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "resolved" and "preprint from bioRxiv" in result.reason
