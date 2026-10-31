"""Extracted pages are remembered between requests.

One marker click re-extracted 912 pages across 17 documents and took 20
seconds, because nothing was cached anywhere.
"""

import pymupdf

from sextant.index import cache


def _pdf(path, text="hello world"):
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_a_second_read_returns_the_same_object(tmp_path):
    cache.clear()
    pdf = _pdf(tmp_path / "a.pdf")

    first = cache.cached_pages(pdf)
    second = cache.cached_pages(pdf)

    assert first is second, "should not have re-extracted"


def test_a_replaced_file_is_read_again(tmp_path):
    """A paper swapped on disk must not serve the old text forever."""
    cache.clear()
    pdf = _pdf(tmp_path / "a.pdf", "original text here")
    before = cache.cached_pages(pdf)

    import os
    _pdf(pdf, "completely different text now")
    os.utime(pdf, (0, 0))          # force a distinct mtime

    after = cache.cached_pages(pdf)
    assert after is not before
    assert "different" in after[0].text


def test_two_different_files_are_cached_separately(tmp_path):
    cache.clear()
    a = _pdf(tmp_path / "a.pdf", "first paper")
    b = _pdf(tmp_path / "b.pdf", "second paper")

    cache.cached_pages(a)
    cache.cached_pages(b)

    assert cache.size() == 2


def test_the_cache_does_not_grow_without_bound(tmp_path):
    cache.clear()
    for n in range(cache.MAX_DOCUMENTS + 5):
        cache.cached_pages(_pdf(tmp_path / f"{n}.pdf", f"paper {n}"))

    assert cache.size() == cache.MAX_DOCUMENTS


def test_an_unreadable_file_is_not_cached_as_a_failure(tmp_path):
    """A file being written should be retried, not held as broken forever."""
    import pytest

    from sextant.index.extract import UnreadablePdfError

    cache.clear()
    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf")

    with pytest.raises(UnreadablePdfError):
        cache.cached_pages(bad)
    assert cache.size() == 0
