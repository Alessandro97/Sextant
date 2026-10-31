from sextant.refs.models import BibEntry, Resolution
from sextant.refs.resolvers import resolve_chain


class Stub:
    def __init__(self, name, result):
        self.name = name
        self._result = result
        self.called = False

    def resolve(self, entry, fetcher, dest_dir):
        self.called = True
        return self._result


ENTRY = BibEntry(key="k", entry_type="article", title="T")


def test_first_resolver_to_return_a_pdf_wins_and_later_ones_do_not_run(tmp_path):
    hit = Stub("first", Resolution(key="k", status="resolved", pdf_path="/tmp/a.pdf"))
    never = Stub("second", Resolution(key="k", status="resolved", pdf_path="/tmp/b.pdf"))

    result = resolve_chain(ENTRY, [hit, never], fetcher=None, dest_dir=tmp_path)

    assert result.pdf_path == "/tmp/a.pdf"
    assert never.called is False


def test_chain_continues_past_resolvers_that_find_nothing(tmp_path):
    miss = Stub("a", Resolution(key="k", status="unresolved", reason="not found"))
    hit = Stub("b", Resolution(key="k", status="resolved", pdf_path="/tmp/b.pdf"))

    result = resolve_chain(ENTRY, [miss, hit], fetcher=None, dest_dir=tmp_path)

    assert result.pdf_path == "/tmp/b.pdf"
    assert result.resolver == "b"


def test_landing_pages_accumulate_across_the_whole_chain(tmp_path):
    """A resolver that cannot fetch the PDF may still know where it lives."""
    a = Stub("a", Resolution(key="k", status="no-pdf", reason="oa flag only",
                             landing_pages=("https://zenodo.org/1",)))
    b = Stub("b", Resolution(key="k", status="no-pdf", reason="no pdf_url",
                             landing_pages=("http://hdl.handle.net/2",)))

    result = resolve_chain(ENTRY, [a, b], fetcher=None, dest_dir=tmp_path)

    assert result.status == "no-pdf"
    assert set(result.landing_pages) == {"https://zenodo.org/1", "http://hdl.handle.net/2"}


def test_a_doi_discovered_mid_chain_is_carried_forward(tmp_path):
    a = Stub("a", Resolution(key="k", status="no-pdf", reason="found it", doi="10.1/x"))
    b = Stub("b", Resolution(key="k", status="unresolved", reason="nope"))

    assert resolve_chain(ENTRY, [a, b], fetcher=None, dest_dir=tmp_path).doi == "10.1/x"


def test_a_resolver_that_raises_does_not_abort_the_chain(tmp_path):
    class Boom:
        name = "boom"

        def resolve(self, entry, fetcher, dest_dir):
            raise RuntimeError("upstream exploded")

    hit = Stub("ok", Resolution(key="k", status="resolved", pdf_path="/tmp/x.pdf"))

    result = resolve_chain(ENTRY, [Boom(), hit], fetcher=None, dest_dir=tmp_path)
    assert result.pdf_path == "/tmp/x.pdf"


def test_exhausting_the_chain_reports_every_reason_tried(tmp_path):
    a = Stub("a", Resolution(key="k", status="unresolved", reason="no doi"))
    b = Stub("b", Resolution(key="k", status="unresolved", reason="no match"))

    result = resolve_chain(ENTRY, [a, b], fetcher=None, dest_dir=tmp_path)

    assert result.status == "unresolved"
    assert "a: no doi" in result.reason and "b: no match" in result.reason


def test_a_source_that_could_not_be_asked_says_so_and_asks_for_a_retry(tmp_path):
    from sextant.refs.http import Unavailable

    class Busy:
        name = "arxiv"

        def resolve(self, entry, fetcher, dest_dir):
            raise Unavailable("HTTP 429")

    miss = Stub("later", Resolution(key="k", status="unresolved", reason="no match"))

    result = resolve_chain(ENTRY, [Busy(), miss], fetcher=None, dest_dir=tmp_path)

    assert result.retry
    assert "arxiv: no answer (HTTP 429), try again later" in result.reason
    assert "no matching" not in result.reason


def test_a_chain_where_every_source_answered_needs_no_retry(tmp_path):
    a = Stub("a", Resolution(key="k", status="unresolved", reason="no doi"))
    assert not resolve_chain(ENTRY, [a], fetcher=None, dest_dir=tmp_path).retry


def test_a_pdf_found_despite_a_busy_source_needs_no_retry(tmp_path):
    from sextant.refs.http import Unavailable

    class Busy:
        name = "busy"

        def resolve(self, entry, fetcher, dest_dir):
            raise Unavailable("HTTP 503")

    hit = Stub("ok", Resolution(key="k", status="resolved", pdf_path="/tmp/x.pdf"))
    assert not resolve_chain(ENTRY, [Busy(), hit], fetcher=None, dest_dir=tmp_path).retry


def test_arxiv_is_asked_last(tmp_path):
    """Three seconds a query, by title: everything cheaper and keyed by DOI
    goes first, and most arXiv copies are listed there already."""
    from sextant.refs.pipeline import build_resolvers
    from sextant.store.db import Store

    store = Store.open(tmp_path / "p.db")
    names = [r.name for r in build_resolvers(store, offline=False)]
    store.close()

    assert names[-1] == "arxiv"
    assert names.index("crossref") < names.index("openalex") < names.index("arxiv")
    published = [names.index(n) for n in ("openalex", "pmc", "unpaywall")]
    assert max(published) < names.index("preprint"), "a preprint after every published copy"


class Recorder:
    name = "later"

    def __init__(self):
        self.seen = None

    def resolve(self, entry, fetcher, dest_dir):
        self.seen = entry
        return Resolution(key=entry.key, status="unresolved", reason="nothing")


def test_a_doi_found_by_one_source_is_handed_to_the_next(tmp_path):
    """Many entries carry no DOI, and every DOI-keyed source after the one
    that found it by title was asked with none."""
    finder = Stub("crossref", Resolution(key="k", status="unresolved", doi="10.5/found"))
    later = Recorder()

    resolve_chain(ENTRY, [finder, later], fetcher=None, dest_dir=tmp_path)

    assert later.seen.doi == "10.5/found"


def test_the_bibliographys_own_doi_is_never_replaced(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title="T", doi="10.5/cited")
    other = Stub("x", Resolution(key="k", status="unresolved", doi="10.5/other"))
    later = Recorder()

    resolve_chain(entry, [other, later], fetcher=None, dest_dir=tmp_path)

    assert later.seen.doi == "10.5/cited"


def test_a_source_that_asks_for_a_retry_itself_is_heard(tmp_path):
    partly = Stub("x", Resolution(key="k", status="unresolved", reason="r", retry=True))
    assert resolve_chain(ENTRY, [partly], fetcher=None, dest_dir=tmp_path).retry


def test_the_doi_reported_is_the_bare_doi(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title="T", doi="https://doi.org/10.5/cited")
    miss = Stub("x", Resolution(key="k", status="unresolved", reason="r"))
    assert resolve_chain(entry, [miss], fetcher=None, dest_dir=tmp_path).doi == "10.5/cited"


def test_the_version_filed_is_reported(tmp_path):
    hit = Stub("arxiv", Resolution(key="k", status="resolved", pdf_path="/tmp/x.pdf",
                                   version="submittedVersion"))
    assert resolve_chain(ENTRY, [hit], fetcher=None, dest_dir=tmp_path).version == "submittedVersion"


def test_a_doi_shown_to_name_another_work_is_not_handed_on(tmp_path):
    """Crossref and OpenAlex refused a .bib DOI that names another paper, and
    PMC then fetched that paper by the same DOI and filed it."""
    entry = BibEntry(key="k", entry_type="article", title="T", doi="10.5/someone-else")
    refusal = Stub("crossref", Resolution(key="k", status="unresolved", wrong_doi=True,
                                          reason="the DOI in the .bib names a different work"))
    later = Recorder()

    resolve_chain(entry, [refusal, later], fetcher=None, dest_dir=tmp_path)

    assert later.seen.doi is None


def test_a_doi_found_by_title_is_marked_as_found(tmp_path):
    finder = Stub("crossref", Resolution(key="k", status="unresolved", doi="10.5/found"))
    later = Recorder()

    resolve_chain(ENTRY, [finder, later], fetcher=None, dest_dir=tmp_path)

    assert later.seen.doi_found


def test_a_preprints_doi_is_handed_on_as_one(tmp_path):
    finder = Stub("crossref", Resolution(key="k", status="unresolved", doi="10.5555/preprint.1",
                                         doi_is_preprint=True))
    later = Recorder()

    resolve_chain(ENTRY, [finder, later], fetcher=None, dest_dir=tmp_path)

    assert later.seen.doi_is_preprint
