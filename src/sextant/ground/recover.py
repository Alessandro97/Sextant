"""Recover a model citation back to an exact, highlightable Span.

THE INVARIANT: an Evidence object exists only if its cited_text was located in
the local text layer of the document and page the API reported. If recovery
fails we return None and the caller records the citation as unverified. We
never paint a highlight we could not confirm.
"""

import difflib
from collections.abc import Sequence

from sextant.index.locate import rects_for_range
from sextant.index.normalize import normalize
from sextant.models import Page, Span

DEFAULT_THRESHOLD = 0.75
#: Matches shorter than this at the edge of a fuzzy match are coincidence.
_EDGE_BLOCK = 3


def recover_span(
    pages: Sequence[Page],
    start_page: int,
    end_page: int,
    cited_text: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> Span | None:
    """Locate cited_text within pages [start_page, end_page] (both inclusive).

    Exact substring match is tried first. Failing that, a similarity-scored
    fuzzy match is accepted only at or above `threshold`, measured as the
    needle's similarity to the candidate region it aligned to. The
    best-scoring page in the range wins.

    The range is treated as inclusive on both ends. The Anthropic citations
    API reports 1-indexed page numbers; treating the end inclusively is
    correct whether the API's end_page_number is inclusive or exclusive, since
    searching one extra page is harmless.
    """
    needle, _ = normalize(cited_text)
    if not needle:
        return None

    lo, hi = min(start_page, end_page), max(start_page, end_page)
    best_score = 0.0
    best_span: Span | None = None

    for page in pages:
        if not lo <= page.number <= hi:
            continue

        haystack, offsets = normalize(page.text)
        hit = _find(haystack, needle, threshold)
        if hit is None:
            continue

        score, n_start, n_end = hit
        char_start = offsets[n_start]
        char_end = offsets[n_end - 1] + 1
        span = Span(
            page=page.number,
            char_start=char_start,
            char_end=char_end,
            rects=rects_for_range(page, char_start, char_end),
        )
        if score > best_score:
            best_score, best_span = score, span

    return best_span


def _find(haystack: str, needle: str, threshold: float) -> tuple[float, int, int] | None:
    """Return (score, start, end) in haystack coordinates, or None.

    The score is the needle's similarity to the CANDIDATE REGION, not to the
    whole page. Scoring against the whole page measures only "do the needle's
    characters appear somewhere, in order" — which any bag of common English
    words satisfies nearly anywhere. Measured on the test fixture, the needle
    "the of and is which a in for to" scored 0.774 that way, sprawling across
    225 characters of a 236-character page and squeaking past the 0.75
    threshold. Scored against its region it is 0.188, correctly rejected,
    while genuine near-misses are unaffected (0.987 and 0.935).
    """
    exact = haystack.find(needle)
    if exact != -1:
        return (1.0, exact, exact + len(needle))

    matcher = difflib.SequenceMatcher(None, haystack, needle, autojunk=False)
    anchor = matcher.find_longest_match(0, len(haystack), 0, len(needle))
    if anchor.size == 0:
        return None

    # Anchor the region on the LONGEST contiguous match and take a
    # needle-sized window around it, rather than bounding it by the outermost
    # matching blocks. Outermost bounding is fragile at the edges: a stray
    # character at either end of the needle can match punctuation far away on
    # the page, stretching the region to the whole page and sinking the score
    # even when an excellent match sits in the middle. Measured on a real
    # 10-page paper, that failure mode cost 100% of recoveries for needles
    # with leading/trailing noise; anchoring recovers all of them, and still
    # rejects the adversarial bag-of-common-words needle.
    # A little slack on each side: the true text can be slightly LONGER than
    # the needle (a dropped character is the common case), and a window sized
    # exactly to the needle would clip the tail off the returned span.
    slack = max(4, len(needle) // 10)
    start = max(0, anchor.a - anchor.b - slack)
    end = min(len(haystack), start + len(needle) + 2 * slack)
    window = difflib.SequenceMatcher(None, haystack[start:end], needle, autojunk=False)
    score = window.ratio()
    if score < threshold:
        return None

    # The slack is for searching, not for painting. Returning the whole window
    # highlighted a few characters either side of the passage that nothing had
    # matched. Bound the span by the first and last real matches instead,
    # ignoring the one- and two-character ones a space or a stray letter makes
    # with the slack.
    blocks = [b for b in window.get_matching_blocks() if b.size >= _EDGE_BLOCK]
    if blocks:
        start, end = start + blocks[0].a, start + blocks[-1].a + blocks[-1].size
    return (score, start, end)
