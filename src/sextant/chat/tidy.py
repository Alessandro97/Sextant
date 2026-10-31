"""Make a span of PDF text fit to show a reader, or a model.

Text sliced out of a page by character offset opens and closes mid-word and
carries the artefacts of print layout: words split across line breaks, author
email addresses, URLs. Sextant was sending that verbatim.

Measured on one real prompt: the statement began "rging as a key enabler"
(emerging), and the first excerpt began "il: {smith, jones}@example.edu).
dimensional space," -- a truncated "email", an affiliation, and another cut
word, before any content at all.
"""

import re

#: A hyphen a line break split: "en- dangered", "het- erogeneous".
_SPLIT_WORD = re.compile(r"(?<=\w)-\s+(?=[a-z])")

#: Contact details that ride along at the top of a first page.
_NOISE = re.compile(r"\S+@\S+\.\S+|https?://\S+|\bdoi:\s*\S+", re.I)

_WORDISH = re.compile(r"[^\W_]")


def word_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Move `start` and `end` off the middle of a word.

    Exact rather than guessed: whether a slice began mid-word is decided by
    looking at the character before it, not by judging whether the first token
    resembles a real word. That judgement is not possible -- "rging" and
    "remote" are equally plausible strings.
    """
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))

    if start > 0 and _WORDISH.match(text[start - 1] or "") and _WORDISH.match(
        text[start] if start < len(text) else " "
    ):
        space = text.find(" ", start)
        start = len(text) if space == -1 else space + 1

    if end < len(text) and _WORDISH.match(text[end]) and end > 0 and _WORDISH.match(
        text[end - 1]
    ):
        space = text.rfind(" ", start, end)
        if space != -1:
            end = space

    return (start, max(start, end))


def tidy(text: str) -> str:
    """Repair a slice of PDF text: rejoin split words, drop contact noise."""
    if not text:
        return ""
    cleaned = _SPLIT_WORD.sub("", text)
    cleaned = _NOISE.sub(" ", cleaned)
    return " ".join(cleaned.split()).strip()


def tidy_slice(text: str, start: int, end: int) -> str:
    """A whole-word, repaired slice of `text`."""
    lo, hi = word_bounds(text, start, end)
    return tidy(text[lo:hi])
