import pymupdf
import pytest

from sextant.index.extract import UnreadablePdfError
from sextant.web.render import PageOutOfRange, page_count, page_png, page_size


def _pdf(path, pages=2):
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72.0, 100.0), f"page {i + 1}", fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_renders_a_page_to_png_bytes(tmp_path):
    data = page_png(_pdf(tmp_path / "a.pdf"), 1, zoom=1.0)

    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_zoom_produces_a_bigger_image(tmp_path):
    pdf = _pdf(tmp_path / "a.pdf")

    assert len(page_png(pdf, 1, zoom=2.0)) > len(page_png(pdf, 1, zoom=1.0))


def test_reports_the_page_count(tmp_path):
    assert page_count(_pdf(tmp_path / "a.pdf", pages=3)) == 3


def test_reports_page_size_in_points(tmp_path):
    width, height = page_size(_pdf(tmp_path / "a.pdf"), 1)

    assert width > 0 and height > 0
    # A4/Letter portrait: taller than wide.
    assert height > width


def test_a_page_number_past_the_end_is_rejected(tmp_path):
    pdf = _pdf(tmp_path / "a.pdf", pages=2)

    with pytest.raises(PageOutOfRange):
        page_png(pdf, 99, zoom=1.0)


def test_page_zero_is_rejected_because_pages_are_one_indexed(tmp_path):
    with pytest.raises(PageOutOfRange):
        page_png(_pdf(tmp_path / "a.pdf"), 0, zoom=1.0)


def test_a_non_pdf_raises_the_domain_error(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf")

    with pytest.raises(UnreadablePdfError):
        page_png(bad, 1, zoom=1.0)


def test_zoom_is_clamped_so_a_url_cannot_request_a_gigapixel_render(tmp_path):
    pdf = _pdf(tmp_path / "a.pdf")

    assert len(page_png(pdf, 1, zoom=500.0)) == len(page_png(pdf, 1, zoom=4.0))
