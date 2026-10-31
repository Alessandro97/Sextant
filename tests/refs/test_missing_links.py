"""What MISSING.md offers for what could not be fetched: the most direct
page a person can open, and copies that may be the work under another title."""

from sextant.refs.folder import materialize
from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry, Resolution
from sextant.refs.resolvers import resolve_chain
from sextant.refs.resolvers.arxiv import ArxivResolver
from sextant.refs.resolvers.itu import ItuResolver, recommendation


def test_an_itu_recommendation_is_recognised_from_its_key_or_title():
    assert recommendation("Calculation of Reference Quantities", "itu_p525") == "P.525"
    assert recommendation("Recommendation ITU-R P.1546: Reference data", "x") == "P.1546"
    assert recommendation("Reference Standard Tables", "ITU-R_P2108") == "P.2108"
    assert recommendation("A Study of Iterative Pruning", "itu2020") is None


def test_an_itu_recommendation_gets_its_own_page(tmp_path):
    entry = BibEntry(key="itu_p525", entry_type="misc",
                     title="Calculation of Reference Quantities and Related Methods")

    result = ItuResolver().resolve(entry, FakeFetcher(), tmp_path)

    assert result.status == "no-pdf"
    assert result.landing_pages == ("https://www.itu.int/rec/R-REC-P.525/en",)
    assert "free" in result.reason


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2501.00001v1</id>
    <title>A Field Study of Seasonal Dynamics of Soil Microbial Communities in Alpine
      Meadows</title>
    <link title="pdf" href="http://arxiv.org/pdf/2501.00001v1" rel="related"/>
  </entry>
</feed>"""


def test_an_arxiv_copy_titled_differently_is_offered_not_filed(tmp_path):
    """The published title is the arXiv one without "A Field Study of": maybe
    the same paper, maybe not, so a person decides."""
    entry = BibEntry(key="k", entry_type="article",
                     title="Seasonal Dynamics of Soil Microbial Communities in Alpine Meadows")
    resolver = ArxivResolver()
    fetcher = FakeFetcher(text_by_url={resolver.search_url(entry.title): FEED})

    result = resolve_chain(entry, [resolver], fetcher, tmp_path)

    assert result.pdf_path is None
    assert result.similar == ("A Field Study of Seasonal Dynamics of Soil Microbial Communities "
                              "in Alpine Meadows — https://arxiv.org/abs/2501.00001v1",)
    assert "http://arxiv.org/pdf/2501.00001v1" not in fetcher.calls

    materialize([result], tmp_path / "refs")
    text = (tmp_path / "refs" / "MISSING.md").read_text()
    assert "Possibly the same work, titled differently" in text
    assert "https://arxiv.org/abs/2501.00001v1" in text


def test_an_unrelated_arxiv_result_is_not_offered(tmp_path):
    entry = BibEntry(key="k", entry_type="article",
                     title="Seasonal Dynamics of Soil Microbial Communities in Alpine Meadows")
    resolver = ArxivResolver()
    other = FEED.replace("A Field Study of Seasonal Dynamics of Soil Microbial Communities in Alpine\n"
                         "      Meadows", "Graph Neural Networks for Molecules")
    fetcher = FakeFetcher(text_by_url={resolver.search_url(entry.title): other})

    assert resolve_chain(entry, [resolver], fetcher, tmp_path).similar == ()


def _filed(key, version, resolver="openalex", reason="preprint from arXiv: the published "
           "version may differ in pages, figures and numbers"):
    return Resolution(key=key, status="resolved", pdf_path=__file__, resolver=resolver,
                      version=version, reason=reason)


def test_a_preprint_filed_in_place_of_the_article_is_listed(tmp_path):
    """A preprint can differ in exactly the figures a citation is checked
    against, and the reader was never told which files were preprints."""
    out = tmp_path / "refs"
    materialize([_filed("pre", "submittedVersion"),
                 _filed("pub", "publishedVersion", reason="")], out)

    text = (out / "MISSING.md").read_text()
    assert "Filed in place of the published version" in text
    assert "`pre`" in text and "`pub`" not in text


def test_the_note_survives_a_later_run_that_finds_the_copy_locally(tmp_path):
    out = tmp_path / "refs"
    materialize([_filed("pre", "submittedVersion")], out)
    materialize([_filed("pre", None, resolver="local", reason="")], out)

    assert "`pre`" in (out / "MISSING.md").read_text()


def test_the_note_goes_once_the_published_version_is_filed(tmp_path):
    out = tmp_path / "refs"
    materialize([_filed("pre", "submittedVersion")], out)
    materialize([_filed("pre", "publishedVersion", reason="")], out)

    assert "`pre`" not in (out / "MISSING.md").read_text()


def test_only_itu_r_series_are_recognised():
    assert recommendation("Ebola in Ituri 2019", "k") is None
    assert recommendation("Coding of Audio Signals", "itu_g711") is None
    assert recommendation("Objective Quality Assessment (ITU-T P.862)", "x") is None


def test_a_recognised_standard_is_not_then_searched_for_by_title(tmp_path):
    """A 3GPP or ITU entry left without a PDF went on to a Crossref search, a
    paid OpenAlex search and an arXiv query."""
    class Later:
        name = "openalex"
        called = False

        def resolve(self, entry, fetcher, dest_dir):
            Later.called = True
            return Resolution(key=entry.key, status="unresolved")

    entry = BibEntry(key="itu_p525", entry_type="misc", title="Calculation of Reference Quantities")

    result = resolve_chain(entry, [ItuResolver(), Later()], FakeFetcher(), tmp_path)

    assert not Later.called
    assert result.landing_pages == ("https://www.itu.int/rec/R-REC-P.525/en",)


def _report(tmp_path, **fields):
    out = tmp_path / "refs"
    materialize([Resolution(key="k", status="unresolved", **fields)], out)
    return (out / "MISSING.md").read_text()


def test_a_title_cannot_forge_sections_or_links(tmp_path):
    """Metadata text went in verbatim: a title with a newline added fake
    entries, and markdown in it disguised where a link leads."""
    text = _report(tmp_path, title="Real title\n## `evil`\n- **Repository copy:** "
                   "[https://doi.org/10.1/x](https://evil.example/x.exe) <img src=x>")

    import re

    assert text.count("\n## ") == 1, "one reference, one entry"
    assert not re.search(r"(?<!\\)\]\(", text), "an unescaped ]( makes a link"
    assert "<img" not in text


def test_only_web_links_are_offered(tmp_path):
    text = _report(tmp_path, landing_pages=("javascript:alert(1)", "https://repo.example/a b",
                                           "https://repo.example/record/1"),
                   similar=("A title — file:///etc/passwd", "Another — https://arxiv.org/abs/1"))

    assert "javascript:" not in text and "file:" not in text and "repo.example/a b" not in text
    assert "<https://repo.example/record/1>" in text
    assert "<https://arxiv.org/abs/1>" in text


def test_a_doi_is_linked_only_when_it_looks_like_one(tmp_path):
    text = _report(tmp_path, doi="10.1/x) [click](https://evil.example")

    assert "https://evil.example" not in text


def test_a_backslash_cannot_undo_the_escaping(tmp_path):
    """A title's own backslash escaped the escape: "\\[" became "\\\\[", a
    literal backslash and then a working link."""
    text = _report(tmp_path, title="\\[Download the corrected PDF\\](https://evil.example/login)")

    # A literal backslash, then a literal bracket: text, not a link.
    assert "\\\\\\[Download" in text and "\\\\\\](https" in text
