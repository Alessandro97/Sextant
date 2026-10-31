"""Question + a paper's pages -> the passages worth quoting.

Deliberately simple: term overlap over a sliding window, each term weighted by
how rare it is in the document being searched. There is no embedding model
here because that would mean either a network call or a large local
dependency.

Plain overlap was enough for a twenty-page paper and useless on a 375-page
specification: every candidate tied at 0.09 -- one common word in eleven --
so "the best four passages" was whichever pages happened to contain "ms", and
the model was handed front matter to judge a citation from. Weighting by
rarity, and measuring a passage against what the document actually contains
rather than against the whole query, moved the same query onto the
specification's reference tables.

Retrieval runs regardless of which backend answers. It is the part that makes
an answer grounded, so even the copy-the-prompt path performs it.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from sextant.chat.tidy import tidy_slice
from sextant.models import Page

#: Sliding window over a page, in characters.
WINDOW = 420
STRIDE = 210

_STOPWORDS = frozenset(
    "a an and are as at be by for from how in is it of on or that the this to "
    "was what when where which who why with does do can".split()
)


@dataclass(frozen=True, slots=True)
class Excerpt:
    page: int
    text: str
    score: float


#: Crude suffix folding so "reached" matches "reach" and "rates" matches
#: "rate". Not a real stemmer, but without it a question phrased in the past
#: tense retrieves nothing from a paper written in the present.
_SUFFIXES = ("ing", "ies", "ed", "es", "s")

#: The same rate written two ways. A manuscript saying "3 Mbit/s" cited a paper
#: whose abstract says "around 3 Mbps per shard", and the two never matched, so
#: the one passage that answered the claim scored on "shard" and "per" alone and
#: lost to pages sharing nothing but common words.
#:
#: Only the unambiguous bit-rate spellings. "MB/s" is deliberately absent:
#: lowercasing loses the case that separates megabytes from megabits, and a
#: tool that must not overclaim cannot afford to equate them.
_UNIT_ALIASES = {
    "bps": "bit/s",
    "kbps": "kbit/s",
    "mbps": "mbit/s",
    "gbps": "gbit/s",
    "tbps": "tbit/s",
}


def _fold(token: str) -> str:
    if token in _UNIT_ALIASES:
        return _UNIT_ALIASES[token]
    # A unit is not a plural. "Mbit/s" folded to "mbit/", which then failed to
    # match the same unit written anywhere else.
    if "/" in token or not token.isalpha():
        return token
    for suffix in _SUFFIXES:
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _terms(text: str) -> set[str]:
    """Comparable words. Punctuation is not part of a word.

    The token pattern admits "." and "/" so that "Mbit/s" and "4.312" survive
    whole -- which also glued on any full stop that ended a sentence, so a
    word at the end of one never matched itself anywhere else. Stripping the
    edges keeps the insides.
    """
    found = re.findall(r"[a-z0-9][a-z0-9./-]*", text.lower())
    cleaned = (t.strip("./-") for t in found)
    return {
        _fold(t) for t in cleaned
        # A bare digit is the whole point of a quantity claim. Dropping
        # everything shorter than two characters threw away the "3" in "3
        # Mbit/s" and left the claim to be found by its common words. Rarity
        # weighting already handles a digit that is on every page.
        if t and t not in _STOPWORDS and (len(t) > 1 or t.isdigit())
    }


def _weights(
    pages: Sequence[Page], wanted: set[str]
) -> tuple[dict[str, float], set[str]]:
    """How much each query term is worth in this document, and which of them
    the document contains at all.

    A term on every page distinguishes nothing; a term on one page
    distinguishes that page. Without this, "ms" and "full" outvoted
    "regeneration" simply by being common.
    """
    if not pages:
        return {term: 1.0 for term in wanted}, set(wanted)

    seen = dict.fromkeys(wanted, 0)
    for page in pages:
        on_page = _terms(page.text)
        for term in wanted:
            if term in on_page:
                seen[term] += 1

    total = len(pages)
    weight = {
        term: math.log((total + 1) / (count + 1)) + 0.1
        for term, count in seen.items()
    }
    return weight, {term for term, count in seen.items() if count}


def top_excerpts(question: str, pages: Sequence[Page], limit: int = 4,
                 window: int = WINDOW, first_page: bool = False) -> list[Excerpt]:
    """Best-matching passages across `pages`, highest score first.

    The score ranks passages WITHIN one document. It is not a measure of
    support and must never be reported as one: measured across this
    manuscript, an unrelated claim scored 0.475 against a random paper, while
    a correctly-cited claim scored 0.216 against the specification it cites.
    Deciding whether a passage backs a claim is the model's job, from the
    passage itself.
    """
    wanted = _terms(question)
    if not wanted:
        return []

    weight, present = _weights(pages, wanted)
    # Only terms the document actually contains. A claim about "batch-level
    # reweighting" cites a specification that never writes "reweighting";
    # dividing by the whole query scored the specification's own reference
    # tables at 0.12 -- indistinguishable from front matter -- because most of
    # the sentence was missing everywhere. What a passage is worth is its share
    # of what this document had to offer.
    full = sum(w for term, w in weight.items() if term in present) or 1.0

    scored: list[Excerpt] = []
    for page in pages:
        for start in range(0, max(1, len(page.text)), max(1, window // 2)):
            # Whole words only. A window sliced by offset opened with "il:
            # {smith, jones}@example.edu)." before any content.
            chunk = tidy_slice(page.text, start, start + window)
            if not chunk.strip():
                continue
            overlap = wanted & _terms(chunk)
            if not overlap:
                continue
            scored.append(
                Excerpt(
                    page=page.number,
                    text=chunk,
                    score=sum(weight[term] for term in overlap) / full,
                )
            )

    scored.sort(key=lambda e: (-e.score, e.page))

    # One excerpt per page: overlapping windows on the same page are near
    # duplicates and would crowd out other pages.
    seen: set[int] = set()
    best: list[Excerpt] = []
    for excerpt in scored:
        if excerpt.page in seen:
            continue
        seen.add(excerpt.page)
        best.append(excerpt)
        if len(best) == limit:
            break

    # The abstract carries the headline number and routinely loses on overlap:
    # it states a result once, in the paper's own words, while a results
    # section repeats the vocabulary of the question. Measured -- a manuscript
    # citing "3 Mbit/s" never retrieved the abstract saying "3 Mbps".
    if first_page and pages and 1 not in seen:
        opening = next((e for e in scored if e.page == 1), None)
        if opening is None:
            head = tidy_slice(pages[0].text, 0, window)
            opening = Excerpt(page=pages[0].number, text=head, score=0.0)
        best = [opening, *best][:max(1, limit)]
    return best
