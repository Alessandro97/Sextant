from pathlib import Path

from sextant.models import Page, Rect, Word
from sextant.store.db import Store


def test_open_creates_schema(tmp_path):
    store = Store.open(tmp_path / "papers.db")
    assert store.list_papers() == []
    store.close()


def test_add_paper_is_idempotent_on_content_hash(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    first = store.add_paper(sample_pdf, title="Sample")
    second = store.add_paper(sample_pdf, title="Sample")

    assert first.id == second.id
    assert len(store.list_papers()) == 1
    store.close()


def test_paper_records_absolute_path_and_never_copies(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    paper = store.add_paper(sample_pdf)

    assert paper.path == str(sample_pdf.resolve())
    assert sample_pdf.exists()
    store.close()


def test_pages_round_trip_with_word_offsets(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    paper = store.add_paper(sample_pdf)
    pages = [
        Page(
            number=1,
            text="the quick",
            words=(
                Word(0, 3, Rect(0.0, 1.0, 2.0, 3.0)),
                Word(4, 9, Rect(4.0, 1.0, 6.0, 3.0)),
            ),
        )
    ]
    store.save_pages(paper.id, pages)

    loaded = store.load_pages(paper.id)
    assert loaded == pages
    store.close()


def test_save_pages_replaces_previous_index(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    paper = store.add_paper(sample_pdf)
    store.save_pages(paper.id, [Page(1, "first", ())])
    store.save_pages(paper.id, [Page(1, "second", ())])

    loaded = store.load_pages(paper.id)
    assert len(loaded) == 1
    assert loaded[0].text == "second"
    store.close()


def test_get_paper_returns_none_for_unknown_id(tmp_path):
    store = Store.open(tmp_path / "papers.db")
    assert store.get_paper("nope") is None
    store.close()


def test_unchanged_file_is_fresh(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    paper = store.add_paper(sample_pdf)
    assert store.staleness(paper) is None
    store.close()


def test_deleted_file_is_reported_missing(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    paper = store.add_paper(sample_pdf)
    sample_pdf.unlink()
    assert store.staleness(paper) == "missing"
    store.close()


def test_edited_file_is_reported_changed(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    paper = store.add_paper(sample_pdf)
    sample_pdf.write_bytes(sample_pdf.read_bytes() + b"% edited\n")
    assert store.staleness(paper) == "changed"
    store.close()


def test_adopt_pdf_copies_into_the_store_and_leaves_the_original(tmp_path, sample_pdf):
    """Downloaded papers belong to the store, not to one manuscript's refs/."""
    store = Store.open(tmp_path / "papers.db")
    paper = store.adopt_pdf(sample_pdf, title="A Downloaded Paper")

    assert Path(paper.path).parent == store.blobs_dir
    assert Path(paper.path).exists()
    assert sample_pdf.exists(), "the source must not be moved or deleted"
    assert len(store.list_papers()) == 1
    store.close()


def test_adopting_the_same_content_twice_stores_one_copy(tmp_path, sample_pdf):
    store = Store.open(tmp_path / "papers.db")
    first = store.adopt_pdf(sample_pdf, title="X")
    second = store.adopt_pdf(sample_pdf, title="X")

    assert first.id == second.id
    assert first.path == second.path
    assert len(list(store.blobs_dir.glob("*.pdf"))) == 1
    store.close()


def test_an_adopted_paper_is_found_by_a_later_lookup(tmp_path, sample_pdf):
    """The whole point: fetch once, and the next manuscript resolves locally."""
    store = Store.open(tmp_path / "papers.db")
    store.adopt_pdf(sample_pdf, title="Seasonal Grazing Patterns in Upland Pastures")

    titles = [p.title for p in store.list_papers()]
    assert "Seasonal Grazing Patterns in Upland Pastures" in titles
    store.close()


def test_add_paper_still_registers_external_files_in_place(tmp_path, sample_pdf):
    """Externally-owned PDFs are never copied — that contract is unchanged."""
    store = Store.open(tmp_path / "papers.db")
    paper = store.add_paper(sample_pdf)

    assert paper.path == str(sample_pdf.resolve())
    assert not store.blobs_dir.exists() or not list(store.blobs_dir.glob("*.pdf"))
    store.close()
