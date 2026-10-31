"""PDF -> Page[], with exact per-word character offsets.

Page.text is constructed here by space-joining words in reading order, rather
than using PyMuPDF's get_text(). This makes the character offsets ours and
exact; get_text() applies its own layout heuristics whose offsets would not
line up with the word rectangles.
"""

from pathlib import Path

import pymupdf

from sextant.models import Page, Rect, Word


class NoTextLayerError(Exception):
    """Raised when a PDF yields no extractable words on any page."""


class UnreadablePdfError(Exception):
    """Raised when the file cannot be opened as a PDF at all.

    Missing, corrupt, or simply not a PDF. Exists so PyMuPDF's own exception
    types never leak past this module: callers degrade on an unreadable file
    the same way they degrade on a missing text layer — as data, not a
    traceback. Plan 2 loops this over ~251 files where a moved path or a bad
    scan is a matter of when, not if.
    """


def extract_pages(pdf_path: Path | str) -> list[Page]:
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        # Deliberately broad: this is an I/O boundary and PyMuPDF raises
        # several unrelated types here (FileNotFoundError, FileDataError,
        # ValueError). Converting all of them to one domain error is the
        # point of this class.
        raise UnreadablePdfError(f"cannot open {pdf_path} as a PDF: {exc}") from exc

    try:
        pages = [_extract_page(doc[i], i + 1) for i in range(doc.page_count)]
    finally:
        doc.close()

    if not any(page.words for page in pages):
        raise NoTextLayerError(f"{pdf_path} has no extractable text layer")

    return pages


def _extract_page(pdf_page: "pymupdf.Page", number: int) -> Page:
    # get_text("words") -> (x0, y0, x1, y1, word, block_no, line_no, word_no)
    raw = pdf_page.get_text("words")
    raw.sort(key=lambda w: (w[5], w[6], w[7]))  # reading order

    parts: list[str] = []
    words: list[Word] = []
    cursor = 0

    for x0, y0, x1, y1, text, *_ in raw:
        if cursor:
            parts.append(" ")
            cursor += 1
        start = cursor
        parts.append(text)
        cursor += len(text)
        words.append(Word(start=start, end=cursor, rect=Rect(x0, y0, x1, y1)))

    return Page(number=number, text="".join(parts), words=tuple(words))
