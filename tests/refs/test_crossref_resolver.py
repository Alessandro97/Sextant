"""Crossref: the DOI for an entry that has none, and publishers' own PDF links."""

import pymupdf

from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry
from sextant.refs.resolvers.crossref import CrossrefResolver, crossref_work_url

TITLE = "Groundwater Recharge in a Karst Aquifer: Evidence from US Watersheds"


def _pdf(title):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(["Regional Hydrology Review", title, "A. Author"]):
        page.insert_text((72, 80 + 14 * i), line, fontsize=10)
    return doc.tobytes()


def _item(doi, title, year, kind="journal-article"):
    return {"DOI": doi, "title": [title], "type": kind,
            "issued": {"date-parts": [[year]]}}


def test_an_entry_without_a_doi_gets_the_one_crossref_finds_for_its_title(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title=TITLE, year="2014")
    resolver = CrossrefResolver()
    fetcher = FakeFetcher(json_by_url={resolver.search_url(entry): {"message": {"items": [
        _item("10.5555/test.2014.0001", TITLE, 2014)]}}})

    result = resolver.resolve(entry, fetcher, tmp_path)

    assert result.doi == "10.5555/test.2014.0001"


def test_a_working_paper_of_another_year_is_not_taken_for_the_article(tmp_path):
    """Crossref ranked a 2011 working paper first for the 2014 journal
    article: the same title, a different document."""
    entry = BibEntry(key="k", entry_type="article", title=TITLE, year="2014")
    resolver = CrossrefResolver()
    fetcher = FakeFetcher(json_by_url={resolver.search_url(entry): {"message": {"items": [
        _item("10.5555/wp.2011.0001",
              "Groundwater Recharge in a Karst Aquifer: Evidence from U.S. Watersheds",
              2011, "report"),
        _item("10.5555/test.2014.0001", TITLE, 2014)]}}})

    assert resolver.resolve(entry, fetcher, tmp_path).doi == "10.5555/test.2014.0001"


def test_a_search_hit_with_another_title_is_not_taken(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title=TITLE, year="2014")
    resolver = CrossrefResolver()
    fetcher = FakeFetcher(json_by_url={resolver.search_url(entry): {"message": {"items": [
        _item("10.5555/test.2014.0002",
              "Groundwater Recharge in a Karst Aquifer: Evidence from Alpine Watersheds", 2014)]}}})

    assert resolver.resolve(entry, fetcher, tmp_path).doi is None


def test_a_publishers_text_mining_pdf_is_downloaded(tmp_path):
    doi = "10.5555/test.2014.0001"
    entry = BibEntry(key="k", entry_type="article", title=TITLE, doi=doi)
    record = {"message": {"DOI": doi, "title": [TITLE], "link": [
        {"URL": "https://pub/x.pdf", "content-type": "application/pdf",
         "content-version": "vor", "intended-application": "text-mining"}]}}
    fetcher = FakeFetcher(json_by_url={crossref_work_url(doi): record},
                          bytes_by_url={"https://pub/x.pdf": _pdf(TITLE)})

    result = CrossrefResolver().resolve(entry, fetcher, tmp_path)

    assert result.status == "resolved"


def test_a_link_registered_for_similarity_checking_is_left_alone(tmp_path):
    """Crossref: such URLs "allow Turnitin to index your content"."""
    doi = "10.5555/test.2013.0003"
    entry = BibEntry(key="k", entry_type="article", title=TITLE, doi=doi)
    record = {"message": {"DOI": doi, "title": [TITLE], "link": [
        {"URL": "https://pub.example/x/pdf", "content-type": "application/pdf",
         "content-version": "vor", "intended-application": "similarity-checking"}]}}
    fetcher = FakeFetcher(json_by_url={crossref_work_url(doi): record},
                          bytes_by_url={"https://pub.example/x/pdf": _pdf(TITLE)})

    result = CrossrefResolver().resolve(entry, fetcher, tmp_path)

    assert result.status != "resolved"
    assert "https://pub.example/x/pdf" not in fetcher.calls


def test_no_email_is_sent_unless_the_reader_set_one():
    entry = BibEntry(key="k", entry_type="article", title=TITLE)
    assert "mailto" not in CrossrefResolver(contact="").search_url(entry)
    assert "mailto=me%40example.org" in CrossrefResolver(contact="me@example.org").search_url(entry)


def test_a_working_paper_that_is_the_only_match_is_taken_and_marked(tmp_path):
    """Filed unmarked, a working paper passed for the article. Marked, every
    copy found under it is filed as a preprint, and listed as one."""
    entry = BibEntry(key="k", entry_type="article", title=TITLE, year="2014")
    resolver = CrossrefResolver()
    fetcher = FakeFetcher(json_by_url={resolver.search_url(entry): {"message": {"items": [
        _item("10.5555/wp.1", TITLE, 2014, "posted-content")]}}})

    result = resolver.resolve(entry, fetcher, tmp_path)

    assert result.doi == "10.5555/wp.1" and result.doi_is_preprint


def test_the_article_is_preferred_to_its_working_paper(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title=TITLE, year="2014")
    resolver = CrossrefResolver()
    fetcher = FakeFetcher(json_by_url={resolver.search_url(entry): {"message": {"items": [
        _item("10.5555/wp.1", TITLE, 2014, "posted-content"),
        _item("10.5555/test.2014.0001", TITLE, 2014)]}}})

    result = resolver.resolve(entry, fetcher, tmp_path)

    assert result.doi == "10.5555/test.2014.0001" and not result.doi_is_preprint


def test_two_works_sharing_a_title_and_year_yield_neither(tmp_path):
    """A conference paper and its journal version: guessing files the wrong one."""
    entry = BibEntry(key="k", entry_type="article", title=TITLE, year="2014")
    resolver = CrossrefResolver()
    fetcher = FakeFetcher(json_by_url={resolver.search_url(entry): {"message": {"items": [
        _item("10.1/conf", TITLE, 2014, "proceedings-article"),
        _item("10.1/jour", TITLE, 2014)]}}})

    result = resolver.resolve(entry, fetcher, tmp_path)

    assert result.doi is None and "several" in result.reason


def test_the_exact_year_is_preferred_to_a_neighbouring_one(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title=TITLE, year="2014")
    resolver = CrossrefResolver()
    fetcher = FakeFetcher(json_by_url={resolver.search_url(entry): {"message": {"items": [
        _item("10.1/early", TITLE, 2013), _item("10.1/right", TITLE, 2014)]}}})

    assert resolver.resolve(entry, fetcher, tmp_path).doi == "10.1/right"


def test_a_preprint_cited_as_an_article_is_found_when_it_is_the_only_match(tmp_path):
    """Biologists cite bioRxiv preprints as @article. Skipping posted-content
    outright lost one that has no journal version at all."""
    entry = BibEntry(key="k", entry_type="article", title=TITLE, year="2017")
    resolver = CrossrefResolver()
    fetcher = FakeFetcher(json_by_url={resolver.search_url(entry): {"message": {"items": [
        _item("10.5555/preprint.2017.0001", TITLE, 2017, "posted-content")]}}})

    result = resolver.resolve(entry, fetcher, tmp_path)

    assert result.doi == "10.5555/preprint.2017.0001"
    assert "preprint" in result.reason
