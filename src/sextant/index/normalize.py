"""Canonicalize text for matching.

The only requirement is that the SAME transform is applied to both the page
text and the model's cited_text. Linguistic accuracy is not the goal;
consistency is.

THE INVARIANT: len(normalized) == len(offsets), every offset is a valid index
into the input, and offsets are non-decreasing. Span recovery indexes offsets
directly, so a violation here does not fail loudly — it silently shifts every
subsequent span, or raises IndexError two layers up. Every branch that appends
to `out` must append to `offsets` exactly as many times.
"""

LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}

DASHES = {
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "−": "-",
}

QUOTES = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
}

# Invisible characters PDF producers embed. All are isspace() == False, so the
# whitespace branch never sees them; unfolded they pass straight through and
# cause invisible, near-undebuggable match failures. Soft hyphen in particular
# is emitted by some producers at every valid hyphenation point in a word,
# whether or not the line actually broke there.
#
# Non-breaking space is deliberately NOT here: it IS isspace(), so the
# whitespace branch already collapses it correctly.
INVISIBLE = {
    "­": "",  # soft hyphen
    "​": "",  # zero-width space
    "‍": "",  # zero-width joiner
}

# One merged dict for lookup, NOT an `or` chain of .get() calls. An `or` chain
# selects the first *truthy* value rather than the first present key, so every
# INVISIBLE entry — which maps to "" — would be silently skipped and the
# character appended verbatim, exactly backwards from deleting it.
_REPLACEMENTS = LIGATURES | DASHES | QUOTES | INVISIBLE


def normalize(text: str) -> tuple[str, list[int]]:
    """Return (normalized_text, offsets).

    offsets[i] is the index in `text` that normalized_text[i] originated from,
    so a match found in normalized space can be mapped back to exact character
    positions in the original.
    """
    out: list[str] = []
    offsets: list[int] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # Line-break hyphenation: "through-\nput" -> "throughput". Accept any
        # dash this module folds, not only ASCII hyphen-minus — otherwise a
        # wrap broken on an en dash folds to "-" and then never rejoins.
        # Only when the continuation is lowercase, so "S-\nBand" survives.
        if (ch == "-" or ch in DASHES) and i + 1 < n and text[i + 1].isspace():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j].islower():
                i = j
                continue

        replacement = _REPLACEMENTS.get(ch)
        if replacement is not None:
            for c in replacement:
                out.append(c)
                offsets.append(i)
            i += 1
            continue

        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                offsets.append(i)
            i += 1
            continue

        # str.lower() can expand one character into several — "İ" (U+0130)
        # lowercases to "i" plus a combining dot. Append per output character
        # so offsets stays 1:1 with out.
        for c in ch.lower():
            out.append(c)
            offsets.append(i)
        i += 1

    while out and out[-1] == " ":
        out.pop()
        offsets.pop()

    return "".join(out), offsets
