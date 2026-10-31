import pymupdf


def _flat(text: str) -> str:
    """Collapse PDF line breaks so phrase checks survive line wrapping.

    get_text() preserves the newlines where lines wrapped in the source PDF,
    so "aggregate write throughput" appears as "aggregate\nwrite throughput".
    Downstream code never reads get_text() — Page.text is space-joined words —
    but this fixture test does, so it flattens first.
    """
    return " ".join(text.split())


def test_sample_pdf_has_two_pages_with_known_text(sample_pdf):
    doc = pymupdf.open(sample_pdf)
    try:
        assert doc.page_count == 2
        assert "aggregate write throughput" in _flat(doc[0].get_text())
        assert "Cold caches" in _flat(doc[1].get_text())
    finally:
        doc.close()


def test_blank_pdf_has_no_text_layer(blank_pdf):
    """Pin the fixture's own contract here, not two tasks downstream.

    Task 4 relies on this PDF yielding zero words. Without this test, a
    PyMuPDF change that leaked stray text would fail inside extract.py and
    send you debugging extraction rather than the fixture.
    """
    doc = pymupdf.open(blank_pdf)
    try:
        assert doc.page_count == 1
        assert doc[0].get_text().strip() == ""
    finally:
        doc.close()
