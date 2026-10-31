from urllib.parse import parse_qs, urlsplit

import pymupdf

from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry
from sextant.refs.resolvers.arxiv import ArxivResolver

TITLE = "Sparse Sampling Designs for Low-Cost Wildlife Monitoring"

FEED = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Query: ti:"{TITLE}"</title>
  <entry>
    <id>http://arxiv.org/abs/2501.12345v1</id>
    <title>{TITLE}</title>
    <link title="pdf" href="http://arxiv.org/pdf/2501.12345v1" rel="related"/>
  </entry>
</feed>"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>arXiv Query: ti:"nothing"</title>
</feed>"""


def test_downloads_the_pdf_when_the_title_matches(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title=TITLE)
    resolver = ArxivResolver()
    fetcher = FakeFetcher(
        text_by_url={resolver.search_url(TITLE): FEED},
        bytes_by_url={"http://arxiv.org/pdf/2501.12345v1": _pdf(TITLE)},
    )

    result = resolver.resolve(entry, fetcher, tmp_path)

    assert result.status == "resolved"
    assert result.pdf_path.endswith("k.pdf")


def test_ignores_a_hit_whose_title_is_a_different_paper(tmp_path):
    """The feed's own <title> echoes the query — never treat it as a result."""
    entry = BibEntry(key="k", entry_type="article", title="A Totally Different Paper")
    resolver = ArxivResolver()
    fetcher = FakeFetcher(text_by_url={resolver.search_url(entry.title): FEED})

    assert resolver.resolve(entry, fetcher, tmp_path).status == "unresolved"


def test_an_empty_feed_resolves_to_nothing(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title="nothing at all here")
    resolver = ArxivResolver()
    fetcher = FakeFetcher(text_by_url={resolver.search_url(entry.title): EMPTY_FEED})

    assert resolver.resolve(entry, fetcher, tmp_path).status == "unresolved"


def test_an_entry_without_a_title_is_skipped(tmp_path):
    entry = BibEntry(key="k", entry_type="misc")
    assert ArxivResolver().resolve(entry, FakeFetcher(), tmp_path).status == "unresolved"


def test_malformed_xml_does_not_raise(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title="x")
    resolver = ArxivResolver()
    fetcher = FakeFetcher(text_by_url={resolver.search_url("x"): "<not xml"})

    assert resolver.resolve(entry, fetcher, tmp_path).status == "unresolved"


def _pdf(title):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(["arXiv:2501.12345v1", title, "A. Author"]):
        page.insert_text((72, 80 + 14 * i), line, fontsize=10)
    return doc.tobytes()


def test_a_download_that_shows_another_paper_is_not_kept(tmp_path):
    """The feed's metadata matched, the file did not: an arXiv listing can
    carry the wrong file for a version, and filing it is worse than nothing."""
    entry = BibEntry(key="k", entry_type="article", title=TITLE)
    resolver = ArxivResolver()
    fetcher = FakeFetcher(
        text_by_url={resolver.search_url(TITLE): FEED},
        bytes_by_url={"http://arxiv.org/pdf/2501.12345v1": _pdf("Some Other Paper Entirely")},
    )

    assert resolver.resolve(entry, fetcher, tmp_path).status == "unresolved"


def test_a_filed_arxiv_copy_is_called_a_preprint(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title=TITLE)
    resolver = ArxivResolver()
    fetcher = FakeFetcher(
        text_by_url={resolver.search_url(TITLE): FEED},
        bytes_by_url={"http://arxiv.org/pdf/2501.12345v1": _pdf(TITLE)},
    )

    assert "preprint from arXiv" in resolver.resolve(entry, fetcher, tmp_path).reason


def test_the_search_asks_for_every_word_not_the_exact_phrase():
    """An exact phrase missed "Cross-Laminated" against "Cross Laminated";
    titles_match decides afterwards, so the search may cast wider."""
    (query,) = parse_qs(urlsplit(ArxivResolver().search_url(
        "Thermal Models for Cross-Laminated Timber: A Survey")).query)["search_query"]

    assert query == ("ti:Thermal AND ti:Models AND ti:Cross AND ti:Laminated AND ti:Timber "
                     "AND ti:Survey")


def test_words_arxiv_does_not_index_are_not_required():
    """"ti:for AND ti:the ..." found nothing for papers that are on arXiv:
    a word the index leaves out can never be matched."""
    (query,) = parse_qs(urlsplit(ArxivResolver().search_url(
        "Nesting patterns for Atlantic sea turtles from the dry season")).query)["search_query"]

    assert query == ("ti:Nesting AND ti:patterns AND ti:Atlantic AND ti:sea AND ti:turtles "
                     "AND ti:dry AND ti:season")


def test_a_title_with_nothing_to_search_on_is_not_sent(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title="高山草甸土壤微生物的季节动态")
    fetcher = FakeFetcher()

    result = ArxivResolver().resolve(entry, fetcher, tmp_path)

    assert fetcher.calls == []
    assert result.status == "unresolved"


def test_a_match_whose_pdf_did_not_answer_is_not_reported_as_absent(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title=TITLE)
    resolver = ArxivResolver()
    fetcher = FakeFetcher(text_by_url={resolver.search_url(TITLE): FEED},
                          errors={"http://arxiv.org/pdf/2501.12345v1"})

    result = resolver.resolve(entry, fetcher, tmp_path)

    assert result.retry
    assert "no matching" not in result.reason and "try again later" in result.reason
