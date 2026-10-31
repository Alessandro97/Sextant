"""Citation markers in a Word-style manuscript.

LaTeX with hyperref hands over the marker rectangle and the bibtex key
directly. A Word document has neither, but Vancouver and AMA styles put the
citation in a superscript run -- and PyMuPDF flags those, so the geometry is
just as exact. What is lost is the key: the number has to be matched against a
numbered reference list rather than read off the link.

Measured on a real proposal: 21 superscript spans at 7pt against 11pt body,
carrying 28 distinct citation numbers, every one resolving to an entry.
"""

import re
from pathlib import Path

import pymupdf

from sextant.manuscript.links import (
    CitationMarker,
    _marker_offset,
    assemble,
)
from sextant.index.cache import cached_pages
from sextant.models import Rect

#: PyMuPDF span flag bit 0 marks a superscript run.
SUPERSCRIPT = 1

#: A superscript of bare digits and separators: "25", "1,2", "12-14".
_CITATION_RUN = re.compile(r"^[\d,–—\-\s]+$")


def _numbers(run: str) -> list[int]:
    """The citation numbers in "1,2" or "12-14"."""
    found: list[int] = []
    for part in re.split(r"[,\s]+", run.strip()):
        if not part:
            continue
        span = re.match(r"^(\d+)[–—-](\d+)$", part)
        if span:
            lo, hi = int(span.group(1)), int(span.group(2))
            if 0 < hi - lo < 40:
                found.extend(range(lo, hi + 1))
            continue
        if part.isdigit():
            found.append(int(part))
    return found


def superscript_markers(pdf_path: Path | str,
                        known: set[str] | None = None) -> list[CitationMarker]:
    """Citation markers read from superscript runs.

    A superscript that is not purely numeric is skipped: footnote daggers and
    ordinal suffixes are superscripts too, and treating them as citations
    would invent references the document does not have. So is a number the
    reference list does not define, when there is a list to ask: an exponent
    is a superscript digit as well.
    """
    pages = cached_pages(pdf_path)
    by_number = {page.number: page for page in pages}

    doc = pymupdf.open(pdf_path)
    try:
        found: list[tuple[int, str, pymupdf.Rect]] = []
        for pdf_page in doc:
            for block in pdf_page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span["text"].strip()
                        if not (span["flags"] & SUPERSCRIPT) or not text:
                            continue
                        if not _CITATION_RUN.match(text):
                            continue
                        for number in _numbers(text):
                            if known and str(number) not in known:
                                continue
                            found.append(
                                (pdf_page.number + 1, str(number),
                                 pymupdf.Rect(span["bbox"]))
                            )
    finally:
        doc.close()

    if not found:
        return []

    by_number = {page.number: page for page in pages}
    located = [
        (page_number, key, rect,
         _marker_offset(by_number.get(page_number), rect)[0])
        for page_number, key, rect in found
    ]
    located.sort(key=lambda item: (item[0], item[3], item[2].x0))

    return assemble(
        [
            (page_number, key, f"[{key}]",
             Rect(rect.x0, rect.y0, rect.x1, rect.y1), offset)
            for page_number, key, rect, offset in located
        ],
        by_number,
    )
