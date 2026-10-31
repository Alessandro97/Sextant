"""OpenAlex lists every copy it knows of, and keeps preprints as works of
their own. Both were being left on the table."""

from urllib.parse import parse_qs, urlsplit

import pymupdf

from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry
from sextant.refs.resolvers.openalex import OpenAlexResolver, work_url

TITLE = "Understanding Coral Reef Recovery After Bleaching Events"
DOI = "10.5555/reef.2023.1"
ENTRY = BibEntry(key="k", entry_type="article", title=TITLE, doi=DOI)


def _pdf(title):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(["Marine Ecology Letters", title, "A. Author"]):
        page.insert_text((72, 80 + 14 * i), line, fontsize=10)
    return doc.tobytes()


def _work(*locations, title=TITLE, work_id="W1", doi=DOI):
    return {"id": f"https://openalex.org/{work_id}", "title": title,
            "doi": f"https://doi.org/{doi}" if doi else None, "locations": list(locations)}


def _loc(pdf, version="publishedVersion", source="Journal", landing=None):
    return {"pdf_url": pdf, "version": version, "landing_page_url": landing,
            "source": {"display_name": source}}


def test_a_later_copy_is_tried_when_the_first_will_not_download(tmp_path):
    """The common case: the publisher's link first, refusing scripts, and a
    repository's copy after it, never tried."""
    work = _work(_loc("https://publisher/x.pdf"),
                 _loc("https://repository.example.edu/x.pdf", "acceptedVersion",
                      "Example University"))
    fetcher = FakeFetcher(json_by_url={work_url(DOI): work},
                          bytes_by_url={"https://repository.example.edu/x.pdf": _pdf(TITLE)})

    result = OpenAlexResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "resolved"
    assert "accepted manuscript from Example University" in result.reason


def test_a_published_copy_says_nothing_about_versions(tmp_path):
    work = _work(_loc("https://repo/x.pdf"))
    fetcher = FakeFetcher(json_by_url={work_url(DOI): work},
                          bytes_by_url={"https://repo/x.pdf": _pdf(TITLE)})

    result = OpenAlexResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "resolved" and "preprint" not in result.reason


def test_a_comma_in_a_title_does_not_split_the_filter():
    """OpenAlex separates filters with commas, so a title holding one became
    two filters and the search failed."""
    url = OpenAlexResolver().search_url("Rivers, Lakes, and Wetlands")
    (value,) = parse_qs(urlsplit(url).query)["filter"]
    assert value == "title.search:Rivers  Lakes  and Wetlands"


def test_a_work_with_a_doi_costs_no_search(tmp_path):
    """Without a key OpenAlex allows $0.10 a day: about 100 searches, and
    lookups by DOI are free. A cold run over a long bibliography spends it all."""
    fetcher = FakeFetcher(json_by_url={work_url(DOI): _work()})

    OpenAlexResolver().resolve(ENTRY, fetcher, tmp_path)

    assert fetcher.calls == [work_url(DOI)]


def test_no_email_address_is_sent():
    """OpenAlex ignores mailto since February 2026, so sending it only
    discloses the reader's address."""
    resolver = OpenAlexResolver(key="")
    assert "mailto" not in work_url(DOI) and "mailto" not in resolver.search_url("T")


def test_a_key_is_sent_when_the_reader_has_one():
    resolver = OpenAlexResolver(key="k123")
    assert "api_key=k123" in resolver.work_url(DOI)
    assert "api_key=k123" in resolver.search_url("T")


def test_a_scan_found_by_a_title_search_is_not_filed(tmp_path):
    resolver = OpenAlexResolver()
    no_doi = BibEntry(key="k", entry_type="article", title=TITLE)
    doc = pymupdf.open(); doc.new_page(); blank = doc.tobytes()
    fetcher = FakeFetcher(
        json_by_url={resolver.search_url(TITLE): {"results": [_work(_loc("https://repo/x.pdf"))]}},
        bytes_by_url={"https://repo/x.pdf": blank})

    assert resolver.resolve(no_doi, fetcher, tmp_path).status != "resolved"


def test_a_preprint_waits_until_every_published_copy_has_been_tried(tmp_path):
    """OpenAlex filed the bioRxiv copy while PMC held the published PDF: the
    preprint belongs to the preprint step, after PMC and Unpaywall."""
    work = _work(_loc("https://publisher/x.pdf"),
                 _loc("https://www.biorxiv.org/x.full.pdf", "submittedVersion", "bioRxiv"))
    fetcher = FakeFetcher(json_by_url={work_url(DOI): work},
                          bytes_by_url={"https://www.biorxiv.org/x.full.pdf": _pdf(TITLE)})

    result = OpenAlexResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status != "resolved"
    assert "https://www.biorxiv.org/x.full.pdf" not in fetcher.calls
