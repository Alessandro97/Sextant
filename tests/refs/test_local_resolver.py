from sextant.refs.models import BibEntry
from sextant.refs.resolvers.local import LocalResolver
from sextant.store.db import Store


def test_finds_a_paper_already_in_the_store_by_title(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    store.add_paper(sample_pdf, title="Rapid Sediment Transport in Braided Rivers")

    entry = BibEntry(key="k", entry_type="article",
                     title="Rapid Sediment Transport in Braided Rivers")
    result = LocalResolver(store).resolve(entry, fetcher=None, dest_dir=tmp_path)

    assert result.status == "resolved"
    assert result.pdf_path == str(sample_pdf.resolve())
    store.close()


def test_hyphenation_difference_still_matches(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    store.add_paper(sample_pdf, title="Multilayered Nonwoven Fabrics")

    entry = BibEntry(key="k", entry_type="article",
                     title="Multi-Layered Non-Woven Fabrics")
    assert LocalResolver(store).resolve(entry, None, tmp_path).status == "resolved"
    store.close()


def test_reports_not_found_rather_than_guessing(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    store.add_paper(sample_pdf, title="Something Entirely Unrelated")

    entry = BibEntry(key="k", entry_type="article", title="Rapid Sediment Transport")
    result = LocalResolver(store).resolve(entry, None, tmp_path)

    assert result.status == "unresolved"
    assert result.pdf_path is None
    store.close()


def test_an_entry_without_a_title_is_not_matched(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    store.add_paper(sample_pdf, title="A Paper")

    entry = BibEntry(key="k", entry_type="misc")
    assert LocalResolver(store).resolve(entry, None, tmp_path).status == "unresolved"
    store.close()


def test_a_stale_store_entry_is_not_offered(tmp_path, sample_pdf):
    """The file was registered, then deleted. Do not hand back a dead path."""
    store = Store.open(tmp_path / "papers.db")
    store.add_paper(sample_pdf, title="A Paper That Is Long Enough")
    sample_pdf.unlink()

    entry = BibEntry(key="k", entry_type="article", title="A Paper That Is Long Enough")
    result = LocalResolver(store).resolve(entry, None, tmp_path)

    assert result.status == "unresolved"
    assert "missing" in result.reason
    store.close()


def test_two_local_papers_answering_to_one_title_are_not_chosen_between(tmp_path):
    """A book called "Coastal Erosion Models" and two papers subtitled from it:
    which one is meant cannot be told from the title, so none is taken."""
    from sextant.refs.http import FakeFetcher
    from sextant.refs.models import BibEntry
    from sextant.refs.resolvers.local import LocalResolver
    from sextant.store.db import Store
    import pymupdf

    store = Store.open(tmp_path / "p.db")
    for name, title in (("a", "Coastal Erosion Models: A Survey"),
                        ("b", "Coastal Erosion Models: Theory and Practice")):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), f"{title} {name}")
        doc.save(tmp_path / f"{name}.pdf")
        doc.close()
        store.adopt_pdf(tmp_path / f"{name}.pdf", title=title)

    entry = BibEntry(key="k", entry_type="book", title="Coastal Erosion Models")
    result = LocalResolver(store).resolve(entry, FakeFetcher(), tmp_path)

    assert result.pdf_path is None


def test_one_paper_stored_twice_is_still_resolved(tmp_path):
    """Two copies of one title are one paper, not an ambiguity."""
    import pymupdf

    from sextant.refs.http import FakeFetcher
    from sextant.refs.models import BibEntry
    from sextant.refs.resolvers.local import LocalResolver
    from sextant.store.db import Store

    store = Store.open(tmp_path / "p.db")
    for name in ("a", "b"):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), f"Coastal Erosion Models: A Survey {name}")
        doc.save(tmp_path / f"{name}.pdf")
        doc.close()
        store.adopt_pdf(tmp_path / f"{name}.pdf", title="Coastal Erosion Models: A Survey")
    entry = BibEntry(key="k", entry_type="book", title="Coastal Erosion Models: A Survey")

    assert LocalResolver(store).resolve(entry, FakeFetcher(), tmp_path).pdf_path
