"""Citations written as "[12]" in the body text.

The third way a manuscript can mark a citation, after hyperref links and
superscript runs. It is the weakest evidence of the three: a bracketed number
is just text, and a document may bracket things that are not citations at all
-- one real proposal wrote "[73]% women" for a figure its author had yet to
fill in.

Two guards make it safe enough to act on. Only numbers that appear as labels
in the reference list are accepted, and the reference list itself is excluded
from the search so its own labels are not read as citations.
"""

import re
from pathlib import Path

from sextant.index.cache import cached_pages
from sextant.index.locate import rects_for_range
from sextant.manuscript.links import (
    CitationMarker,
    _marker_offset,
    assemble,
)
from sextant.models import Page, Rect

#: One bracket: "[12]", "[3, 7]", "[1-3]", "[1, 3–5, 8]".
_BRACKETED = re.compile(r"\[(\d{1,3}(?:\s*[,;–—-]\s*\d{1,3})*)\]")
#: One item inside it. Only a dash makes a range; a comma separates.
_ITEM = re.compile(r"(\d{1,3})(?:\s*[–—-]\s*(\d{1,3}))?")
#: What joins two brackets into one range, as in IEEE's "[12]–[14]".
_BRIDGE = re.compile(r"\s*[–—-]\s*")
#: The widest range believed. Anything wider is a page range or a typo.
_MAX_RANGE = 40


def _span(lo: int, hi: int) -> list[int]:
    """lo..hi inclusive when that is a believable run of citations, else lo."""
    return list(range(lo, hi + 1)) if 0 < hi - lo < _MAX_RANGE else [lo]


def _numbers(inner: str) -> list[int]:
    """The citations one bracket names, in the order it names them."""
    out: list[int] = []
    for item in re.split(r"\s*[,;]\s*", inner):
        match = _ITEM.fullmatch(item)
        if match:
            lo, hi = match.group(1), match.group(2)
            out += _span(int(lo), int(hi)) if hi else [int(lo)]
    return out

#: Where a reference list starts. Everything after this is labels, not
#: citations, and reading it as prose invents one citation per entry.
#:
#: No lookahead: a reference list begins exactly "References [1]", so a guard
#: against a following number never matched the real thing, and the list's own
#: labels were counted as citations -- 30 markers for 15 references. The last
#: occurrence is used instead, since papers name the word in prose first.
_HEADING = re.compile(r"\b(?:REFERENCES|References|BIBLIOGRAPHY|Bibliography)\b")


def _reference_start(pages: list[Page]) -> tuple[int, int]:
    """(page number, char offset) where the reference list begins."""
    for page in reversed(pages):
        matches = list(_HEADING.finditer(page.text))
        if matches:
            return (page.number, matches[-1].start())
    return (10**6, 0)


def bracketed_markers(pdf_path: Path | str, known: set[str]) -> list[CitationMarker]:
    """Citations marked "[N]" in the body, for N the reference list knows.

    `known` is what makes this trustworthy: a bracketed number with no matching
    entry is a placeholder, an equation tag or a page range, and is skipped.
    """
    if not known:
        return []

    pages = cached_pages(pdf_path)
    stop_page, stop_offset = _reference_start(pages)

    found: list[tuple[int, str, int, int]] = []
    for page in pages:
        if page.number > stop_page:
            break
        previous = None
        for match in _BRACKETED.finditer(page.text):
            if page.number == stop_page and match.start() >= stop_offset:
                break
            numbers = _numbers(match.group(1))
            if previous is not None and len(numbers) == 1 \
                    and _BRIDGE.fullmatch(page.text, previous.end(), match.start()):
                # "[12]–[14]": the brackets name the ends, and 13 is cited too.
                first = _numbers(previous.group(1))[-1]
                numbers = _span(first, numbers[0])[1:] or numbers
            previous = match
            for number in map(str, numbers):
                if number in known:
                    found.append((page.number, number, match.start(), match.end()))

    if not found:
        return []

    by_number = {page.number: page for page in pages}
    out = []
    for page_number, key, start_at, end_at in found:
        rects = rects_for_range(by_number[page_number], start_at, end_at)
        rect = (
            Rect(min(r.x0 for r in rects), min(r.y0 for r in rects),
                 max(r.x1 for r in rects), max(r.y1 for r in rects))
            if rects else Rect(0.0, 0.0, 0.0, 0.0)
        )
        out.append((page_number, key, f"[{key}]", rect, start_at))

    return assemble(out, by_number)
