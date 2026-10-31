"""Getting a PDF from the places that say they have one.

Sources list several copies of a work -- the publisher's, a repository's, a
preprint -- and the first is often a publisher link that refuses scripts.
Each copy is tried in turn, the best version first, and a file is kept only
when it shows the work that was cited.
"""

import pymupdf
import pytest

from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry
from sextant.refs.resolvers.copies import Copy, fetch_first

TITLE = "Seasonal Dynamics of Soil Microbial Communities in Alpine Meadows"
ENTRY = BibEntry(key="k", entry_type="article", title=TITLE, doi="10.1234/soil.2020.5")


def _pdf(*lines, pages=1):
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page()
        if n == 0:
            for i, line in enumerate(lines):
                page.insert_text((72.0, 80.0 + 14 * i), line, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


THE_PAPER = _pdf("Journal of Soil Ecology 12 (2020)", TITLE, "A. Author, B. Author",
                 "Abstract. We sampled ...")
ANOTHER = _pdf("Journal of Soil Ecology 12 (2020)",
               "Nitrogen Uptake by Grasses Under Drought", "C. Author")
BLANK = _pdf()


def test_a_published_copy_is_tried_before_a_preprint_listed_first(tmp_path):
    fetcher = FakeFetcher(bytes_by_url={"https://pre/x.pdf": THE_PAPER,
                                        "https://pub/x.pdf": THE_PAPER})
    copies = [Copy("https://pre/x.pdf", version="submittedVersion"),
              Copy("https://pub/x.pdf", version="publishedVersion")]

    got, _, _ = fetch_first(ENTRY, copies, fetcher, tmp_path)

    assert got.copy.url == "https://pub/x.pdf"
    assert fetcher.calls == ["https://pub/x.pdf"]


def test_a_copy_that_will_not_download_gives_way_to_the_next(tmp_path):
    """The publisher's link came first and refused scripts; the repository's
    copy after it was never tried."""
    fetcher = FakeFetcher(bytes_by_url={"https://repo/x.pdf": THE_PAPER})
    copies = [Copy("https://publisher/x.pdf", version="publishedVersion"),
              Copy("https://repo/x.pdf", version="publishedVersion")]

    got, _, _ = fetch_first(ENTRY, copies, fetcher, tmp_path)

    assert got.copy.url == "https://repo/x.pdf"
    assert got.path.read_bytes() == THE_PAPER


def test_a_copy_of_another_work_is_not_kept(tmp_path):
    """Filing the wrong paper is worse than filing none."""
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": ANOTHER,
                                        "https://b/x.pdf": THE_PAPER})
    copies = [Copy("https://a/x.pdf"), Copy("https://b/x.pdf")]

    got, notes, _ = fetch_first(ENTRY, copies, fetcher, tmp_path)

    assert got.copy.url == "https://b/x.pdf"
    assert any("a" in note and "does not show" in note for note in notes)


def test_nothing_is_left_behind_when_no_copy_is_the_work(tmp_path):
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": ANOTHER})

    got, notes, _ = fetch_first(ENTRY, [Copy("https://a/x.pdf")], fetcher, tmp_path)

    assert got is None
    assert not any(tmp_path.iterdir())
    assert notes


def test_the_doi_on_the_page_is_enough(tmp_path):
    """A translated or retitled version still prints its DOI."""
    page = _pdf("Saisonale Dynamik mikrobieller Gemeinschaften", "doi:10.1234/soil.2020.5")
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": page})

    got, _, _ = fetch_first(ENTRY, [Copy("https://a/x.pdf")], fetcher, tmp_path)

    assert got is not None


def test_a_title_after_a_repository_cover_page_is_found(tmp_path):
    """Repositories put a cover sheet in front of the article."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 80), "Deposited in the University Repository", fontsize=10)
    article = doc.new_page()
    for i, line in enumerate(["Journal of Soil Ecology", TITLE, "A. Author"]):
        article.insert_text((72, 80 + 14 * i), line, fontsize=10)
    fetcher = FakeFetcher(bytes_by_url={"https://repo/x.pdf": doc.tobytes()})

    got, _, _ = fetch_first(ENTRY, [Copy("https://repo/x.pdf")], fetcher, tmp_path)

    assert got is not None


@pytest.mark.parametrize("keyed, kept", [(True, True), (False, False)])
def test_a_scan_is_kept_only_when_the_source_named_the_work_by_its_doi(tmp_path, keyed, kept):
    """Nothing on a page without text can confirm or refute it. A copy the
    source listed under the DOI was not guessed; one found by a title search
    might have been."""
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": BLANK})

    got, _, _ = fetch_first(ENTRY, [Copy("https://a/x.pdf", keyed_by_doi=keyed)],
                         fetcher, tmp_path)

    assert (got is not None) == kept


def test_the_same_url_listed_twice_is_asked_for_once(tmp_path):
    fetcher = FakeFetcher()
    fetch_first(ENTRY, [Copy("https://a/x.pdf"), Copy("https://a/x.pdf")], fetcher, tmp_path)
    assert fetcher.calls == ["https://a/x.pdf"]


def test_a_notice_about_the_work_is_not_the_work(tmp_path):
    """OpenAlex can list an erratum as a journal paper's PDF. It reprints the
    title, so the title check alone would have filed it."""
    erratum = _pdf("Erratum on:", TITLE, "by A. Author and B. Author",
                   "There were errors in lines 303 and 337 of the code ...")
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": erratum})

    got, notes, _ = fetch_first(ENTRY, [Copy("https://a/x.pdf")], fetcher, tmp_path)

    assert got is None
    assert any("notice" in note for note in notes)


def test_a_work_that_is_itself_a_correction_can_be_fetched(tmp_path):
    entry = BibEntry(key="k", entry_type="article",
                     title="Correction to: Seasonal Dynamics of Soil Microbes")
    page = _pdf("Correction to: Seasonal Dynamics of Soil Microbes", "A. Author")
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": page})

    got, _, _ = fetch_first(entry, [Copy("https://a/x.pdf")], fetcher, tmp_path)

    assert got is not None


def test_a_copy_that_would_not_download_is_said_so(tmp_path):
    """arXiv matched, its PDF did not download, and the miss read "no matching
    arxiv entry" -- a not-found for a paper that is there."""
    got, notes, retry = fetch_first(ENTRY, [Copy("https://publisher/x.pdf")], FakeFetcher(), tmp_path)

    assert got is None and not retry
    assert any("would not download" in note and "publisher" in note for note in notes)


def test_a_copy_whose_host_did_not_answer_asks_for_a_retry(tmp_path):
    fetcher = FakeFetcher(errors={"https://busy/x.pdf"})

    got, notes, retry = fetch_first(ENTRY, [Copy("https://busy/x.pdf")], fetcher, tmp_path)

    assert got is None and retry
    assert any("try again later" in note for note in notes)


def test_no_more_than_a_few_copies_are_tried(tmp_path):
    """One record can list hundreds of URLs, each a connect timeout."""
    copies = [Copy(f"https://h{n}/x.pdf") for n in range(50)]
    fetcher = FakeFetcher()

    fetch_first(ENTRY, copies, fetcher, tmp_path)

    assert len(fetcher.calls) == 8


def test_copies_of_one_rank_are_tried_in_the_order_listed(tmp_path):
    fetcher = FakeFetcher()
    fetch_first(ENTRY, [Copy("https://a/x.pdf"), Copy("https://b/x.pdf"), Copy("https://a/x.pdf")],
                fetcher, tmp_path)
    assert fetcher.calls == ["https://a/x.pdf", "https://b/x.pdf"]


def test_a_scan_is_not_kept_under_a_doi_found_by_title(tmp_path):
    """A DOI a title search found is a guess, and a scan cannot confirm it."""
    found = BibEntry(key="k", entry_type="article", title=TITLE, doi="10.1234/soil.2020.5",
                     doi_found=True)
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": BLANK})

    got, _, _ = fetch_first(found, [Copy("https://a/x.pdf")], fetcher, tmp_path)

    assert got is None


def test_a_doi_in_another_papers_references_is_not_enough(tmp_path):
    """Page two of a different paper cited the DOI in its reference list."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 80), "Nitrogen Uptake by Grasses Under Drought", fontsize=10)
    refs = doc.new_page()
    refs.insert_text((72, 80), "References", fontsize=10)
    refs.insert_text((72, 94), "[1] A. Author, doi:10.1234/soil.2020.5", fontsize=10)
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": doc.tobytes()})

    got, _, _ = fetch_first(ENTRY, [Copy("https://a/x.pdf")], fetcher, tmp_path)

    assert got is None


@pytest.mark.parametrize("opening", ["Comment on:", "Reply to", "Response to", "Addendum to:"])
def test_a_comment_or_reply_is_not_the_work(tmp_path, opening):
    page = _pdf(opening, TITLE, "by C. Critic")
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": page})

    got, _, _ = fetch_first(ENTRY, [Copy("https://a/x.pdf")], fetcher, tmp_path)

    assert got is None


def test_a_notice_word_inside_a_sentence_is_not_a_notice(tmp_path):
    """"Rofecoxib was withdrawn..." in an abstract refused the paper everywhere."""
    page = _pdf("Journal of Soil Ecology", TITLE, "Abstract. The fungicide was withdrawn in 2004 ...")
    fetcher = FakeFetcher(bytes_by_url={"https://a/x.pdf": page})

    got, _, _ = fetch_first(ENTRY, [Copy("https://a/x.pdf")], fetcher, tmp_path)

    assert got is not None


def test_a_copy_found_under_a_preprints_doi_is_a_preprint(tmp_path):
    """OpenAlex labels a bioRxiv copy acceptedVersion; under a DOI Crossref
    calls a preprint's, it is filed and listed as one."""
    entry = BibEntry(key="k", entry_type="article", title=TITLE, doi="10.5555/preprint.1",
                     doi_found=True, doi_is_preprint=True)
    fetcher = FakeFetcher(bytes_by_url={"https://www.biorxiv.org/x.pdf": THE_PAPER})

    got, _, _ = fetch_first(entry, [Copy("https://www.biorxiv.org/x.pdf", version="acceptedVersion",
                                         source="bioRxiv")], fetcher, tmp_path)

    assert got.copy.version == "submittedVersion"
