from pathlib import Path

from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry
from sextant.refs.resolvers.openalex import OpenAlexResolver, work_url
from sextant.refs.resolvers.unpaywall import UnpaywallResolver, unpaywall_url

DOI = "10.5555/test.2017.0001"
CONTACT = "reader@example.org"
ENTRY = BibEntry(key="k", entry_type="article", title="Rapid Sediment Transport", doi=DOI)

OA_FLAGGED_NO_PDF = {
    "title": "Rapid Sediment Transport",
    "doi": f"https://doi.org/{DOI}",
    "open_access": {"is_oa": True, "oa_status": "green"},
    "locations": [
        {"pdf_url": None, "landing_page_url": "https://zenodo.org/record/1234567"},
        {"pdf_url": None, "landing_page_url": "http://hdl.handle.net/1234/56789"},
    ],
}

WITH_REAL_PDF = {
    "title": "Rapid Sediment Transport",
    "doi": f"https://doi.org/{DOI}",
    "open_access": {"is_oa": True, "oa_status": "gold"},
    "locations": [{"pdf_url": "https://repo/paper.pdf",
                   "landing_page_url": "https://repo/record/1"}],
}


def test_openalex_does_not_claim_success_when_every_pdf_url_is_null(tmp_path):
    """is_oa True with no pdf_url anywhere. Measured against the live API."""
    fetcher = FakeFetcher(json_by_url={work_url(DOI): OA_FLAGGED_NO_PDF})

    result = OpenAlexResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.pdf_path is None
    assert result.status == "no-pdf"


def test_openalex_harvests_landing_pages_for_manual_retrieval(tmp_path):
    fetcher = FakeFetcher(json_by_url={work_url(DOI): OA_FLAGGED_NO_PDF})

    result = OpenAlexResolver().resolve(ENTRY, fetcher, tmp_path)

    assert "https://zenodo.org/record/1234567" in result.landing_pages
    assert "http://hdl.handle.net/1234/56789" in result.landing_pages


def test_openalex_downloads_when_a_real_pdf_url_exists(tmp_path):
    fetcher = FakeFetcher(
        json_by_url={work_url(DOI): WITH_REAL_PDF},
        bytes_by_url={"https://repo/paper.pdf": b"%PDF-1.7 body"},
    )

    result = OpenAlexResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "resolved"
    assert result.pdf_path is not None
    assert Path(result.pdf_path).read_bytes().startswith(b"%PDF")


def test_openalex_finds_a_doi_by_title_when_the_entry_has_none(tmp_path):
    """Many bibliography entries carry no DOI at all."""
    no_doi = BibEntry(key="k", entry_type="article",
                      title="Multilayered Nonwoven Fabrics for Hierarchical Air Filtration")
    search = {"results": [{"title": no_doi.title,
                           "doi": "https://doi.org/10.5555/test.2021.0002",
                           "open_access": {"is_oa": False},
                           "locations": []}]}
    fetcher = FakeFetcher(json_by_url={OpenAlexResolver().search_url(no_doi.title): search})

    result = OpenAlexResolver().resolve(no_doi, fetcher, tmp_path)

    assert result.doi == "10.5555/test.2021.0002"


def test_openalex_ignores_a_title_search_hit_for_a_different_paper(tmp_path):
    no_doi = BibEntry(key="k", entry_type="article", title="A Very Specific Paper Title")
    search = {"results": [{"title": "Something Completely Different",
                           "doi": "https://doi.org/10.1/wrong",
                           "locations": []}]}
    fetcher = FakeFetcher(json_by_url={OpenAlexResolver().search_url(no_doi.title): search})

    assert OpenAlexResolver().resolve(no_doi, fetcher, tmp_path).doi is None


def test_unpaywall_requires_a_real_pdf_url_too(tmp_path):
    fetcher = FakeFetcher(json_by_url={
        unpaywall_url(DOI, CONTACT): {"is_oa": True,
                             "best_oa_location": {"url_for_pdf": None,
                                                  "url": "https://repo/landing"}},
    })

    result = UnpaywallResolver(contact=CONTACT).resolve(ENTRY, fetcher, tmp_path)

    assert result.pdf_path is None
    assert "https://repo/landing" in result.landing_pages


def test_unpaywall_downloads_a_real_pdf(tmp_path):
    fetcher = FakeFetcher(
        json_by_url={unpaywall_url(DOI, CONTACT): {
            "is_oa": True,
            "best_oa_location": {"url_for_pdf": "https://repo/p.pdf"}}},
        bytes_by_url={"https://repo/p.pdf": b"%PDF-1.7 body"},
    )

    assert UnpaywallResolver(contact=CONTACT).resolve(ENTRY, fetcher, tmp_path).status == "resolved"


def test_resolvers_skip_entries_with_no_doi_and_no_title(tmp_path):
    bare = BibEntry(key="k", entry_type="misc")
    assert UnpaywallResolver(contact=CONTACT).resolve(bare, FakeFetcher(), tmp_path).status == "unresolved"


def test_a_download_stays_inside_the_folder_it_was_given(tmp_path):
    """The key names the file, and the key comes from someone's manuscript."""
    hostile = BibEntry(key="../../escape", entry_type="article",
                       title="Rapid Sediment Transport", doi=DOI)
    fetcher = FakeFetcher(
        json_by_url={work_url(DOI): WITH_REAL_PDF},
        bytes_by_url={"https://repo/paper.pdf": b"%PDF-1.7 body"},
    )
    staging = tmp_path / "refs" / ".downloads"

    result = OpenAlexResolver().resolve(hostile, fetcher, staging)

    assert Path(result.pdf_path).parent == staging
    assert not (tmp_path / "escape.pdf").exists()


def test_a_doi_naming_a_different_paper_is_not_downloaded(tmp_path):
    """linkcheck exists because wrong DOIs are common, and fetch trusted them:
    the entry got the other paper's PDF, and its title."""
    wrong = BibEntry(key="k", entry_type="article", title="Glacier Retreat and Alpine Plant Migration",
                     doi=DOI)
    fetcher = FakeFetcher(
        json_by_url={work_url(DOI): WITH_REAL_PDF,
                     unpaywall_url(DOI, CONTACT): {"title": "Rapid Sediment Transport",
                                          "is_oa": True,
                                          "best_oa_location": {"url_for_pdf": "https://repo/p.pdf"}}},
        bytes_by_url={"https://repo/paper.pdf": b"%PDF-1.7 body",
                      "https://repo/p.pdf": b"%PDF-1.7 body"},
    )

    for resolver in (OpenAlexResolver(), UnpaywallResolver(contact=CONTACT)):
        result = resolver.resolve(wrong, fetcher, tmp_path / resolver.name)
        assert result.pdf_path is None, resolver.name
        assert "different" in result.reason, resolver.name


def test_unpaywall_is_not_asked_without_a_contact(tmp_path):
    """It refuses every request without an email (422), and each refusal read
    as "not found in unpaywall" for papers it holds. No address is made up."""
    fetcher = FakeFetcher()

    result = UnpaywallResolver(contact="").resolve(ENTRY, fetcher, tmp_path)

    assert fetcher.calls == []
    assert "SEXTANT_CONTACT" in result.reason


def test_unpaywall_tries_every_open_location(tmp_path):
    """best_oa_location is one of oa_locations, and often the publisher's."""
    fetcher = FakeFetcher(
        json_by_url={unpaywall_url(DOI, CONTACT): {
            "title": "Rapid Sediment Transport", "is_oa": True,
            "best_oa_location": {"url_for_pdf": "https://publisher/p.pdf",
                                 "version": "publishedVersion"},
            "oa_locations": [
                {"url_for_pdf": "https://publisher/p.pdf", "version": "publishedVersion"},
                {"url_for_pdf": "https://repo/p.pdf", "version": "acceptedVersion",
                 "url": "https://repo/record"},
            ]}},
        bytes_by_url={"https://repo/p.pdf": b"%PDF-1.7 body"},
    )

    result = UnpaywallResolver(contact=CONTACT).resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "resolved"
    assert "accepted manuscript" in result.reason
    assert fetcher.calls[1:] == ["https://publisher/p.pdf", "https://repo/p.pdf"]
