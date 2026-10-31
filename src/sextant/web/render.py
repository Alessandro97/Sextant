"""PDF page -> PNG bytes.

Zoom is clamped. The zoom factor arrives from a URL query parameter, and an
unclamped value lets any caller ask for a render large enough to exhaust
memory on a machine that is also the user's workstation.
"""

from pathlib import Path

import pymupdf

from sextant.index.extract import UnreadablePdfError

MAX_ZOOM = 4.0
MIN_ZOOM = 0.25


class PageOutOfRange(Exception):
    """Raised when a 1-indexed page number does not exist in the document."""


def _open(pdf_path: Path | str) -> "pymupdf.Document":
    try:
        return pymupdf.open(pdf_path)
    except Exception as exc:
        raise UnreadablePdfError(f"cannot open {pdf_path} as a PDF: {exc}") from exc


def page_count(pdf_path: Path | str) -> int:
    doc = _open(pdf_path)
    try:
        return doc.page_count
    finally:
        doc.close()


def page_size(pdf_path: Path | str, number: int) -> tuple[float, float]:
    """(width, height) in points for a 1-indexed page."""
    doc = _open(pdf_path)
    try:
        _require_in_range(doc, number)
        rect = doc[number - 1].rect
        return (rect.width, rect.height)
    finally:
        doc.close()


def page_png(pdf_path: Path | str, number: int, zoom: float = 1.5) -> bytes:
    """Render a 1-indexed page to PNG bytes."""
    zoom = min(MAX_ZOOM, max(MIN_ZOOM, zoom))
    doc = _open(pdf_path)
    try:
        _require_in_range(doc, number)
        pix = doc[number - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pix.tobytes("png")
    finally:
        doc.close()


def _require_in_range(doc: "pymupdf.Document", number: int) -> None:
    if number < 1 or number > doc.page_count:
        raise PageOutOfRange(f"page {number} outside 1..{doc.page_count}")
