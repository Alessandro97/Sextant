import pytest

from sextant.index.extract import (
    NoTextLayerError,
    UnreadablePdfError,
    extract_pages,
)


def test_extracts_both_pages_one_indexed(sample_pdf):
    pages = extract_pages(sample_pdf)
    assert [p.number for p in pages] == [1, 2]


def test_page_text_contains_expected_content(sample_pdf):
    pages = extract_pages(sample_pdf)
    assert "aggregate write throughput" in pages[0].text
    assert "Cold caches" in pages[1].text


def test_every_word_offset_slices_back_to_its_own_text(sample_pdf):
    """The core invariant of extraction: offsets are exact, not approximate."""
    for page in extract_pages(sample_pdf):
        assert page.words, f"page {page.number} produced no words"
        for word in page.words:
            sliced = page.text[word.start : word.end]
            assert sliced.strip() == sliced
            assert " " not in sliced


def test_word_rects_are_non_degenerate(sample_pdf):
    page = extract_pages(sample_pdf)[0]
    for word in page.words:
        assert word.rect.x1 > word.rect.x0
        assert word.rect.y1 > word.rect.y0


def test_pdf_without_text_layer_raises(blank_pdf):
    with pytest.raises(NoTextLayerError):
        extract_pages(blank_pdf)


def test_missing_file_raises_our_error_not_pymupdfs(tmp_path):
    """PyMuPDF's exception types must not leak past this module."""
    with pytest.raises(UnreadablePdfError):
        extract_pages(tmp_path / "does-not-exist.pdf")


def test_corrupt_file_raises_our_error_not_pymupdfs(tmp_path):
    not_a_pdf = tmp_path / "corrupt.pdf"
    not_a_pdf.write_text("this is plainly not a PDF")

    with pytest.raises(UnreadablePdfError):
        extract_pages(not_a_pdf)
