"""Find a phrase in a document and say exactly where it is.

Built on the same offsets and word rectangles as every other highlight in
Sextant, so a search hit is located the same way a verified quantity is: by
character range in the page's own text, mapped back to the words that produced
it. Nothing is painted that was not found.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sextant.index.locate import rects_for_range
from sextant.models import Page, Span

#: Enough to page through; beyond this a reader wants a better query.
MAX_HITS = 200

#: Words split across a line break are joined in the page text with a hyphen
#: and a space, so a search for "endangered" should still find
#: "en- dangered".
_FLEX = r"-?\s*"


@dataclass(frozen=True, slots=True)
class Hit:
    span: Span
    text: str


def _pattern(query: str) -> re.Pattern[str] | None:
    words = [w for w in re.split(r"\s+", query.strip()) if w]
    if not words:
        return None
    # Between characters of a word, tolerate the hyphen a line break inserts;
    # between words, any whitespace.
    parts = []
    for word in words:
        parts.append(_FLEX.join(re.escape(c) for c in word))
    return re.compile(r"\s+".join(parts), re.IGNORECASE)


def find_all(
    pages: Sequence[Page], query: str, limit: int = MAX_HITS
) -> tuple[list[Hit], int]:
    """Every occurrence of `query`, and how many there are in total."""
    pattern = _pattern(query)
    if pattern is None:
        return ([], 0)

    hits: list[Hit] = []
    total = 0
    for page in pages:
        for match in pattern.finditer(page.text):
            total += 1
            if len(hits) >= limit:
                continue
            start, end = match.start(), match.end()
            hits.append(
                Hit(
                    span=Span(
                        page=page.number,
                        char_start=start,
                        char_end=end,
                        rects=rects_for_range(page, start, end),
                    ),
                    text=" ".join(
                        page.text[max(0, start - 40) : end + 40].split()
                    ),
                )
            )
    return (hits, total)
