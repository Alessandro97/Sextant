"""LaTeX source -> prose, for quantity extraction only.

Not a general LaTeX renderer. The single requirement is that numbers and their
units survive intact and adjacent, because that adjacency is what screen.py
matches on. Everything else may be approximated.
"""

import re

# \cite/\ref/\label contribute nothing to a claim and their arguments are keys,
# not prose. Delete argument and all.
_DROPPED = re.compile(
    r"\\(?:label|ref|eqref|autoref|cref|Cref|citep|citet|autocite|cite[tp]?)\*?"
    r"\s*(?:\[[^\]]*\])*\s*\{[^}]*\}"
)

# \gls{pcr} -> pcr. The term inside IS the prose. Longest alternatives first so
# \textbf is never partially consumed by \text.
_UNWRAPPED = re.compile(
    r"\\(?:textbf|textit|texttt|textrm|text|mathrm|mathbf|glspl|Glspl|gls|Gls|emph)"
    r"\s*\{([^{}]*)\}"
)

# An escaped percent is a unit, not a comment. Protect it before macro removal
# strips the backslash.
_PERCENT_SENTINEL = "\x00PCT\x00"


def detex(source: str) -> str:
    """Reduce LaTeX to readable prose, preserving number/unit adjacency."""
    text = source.replace(r"\%", _PERCENT_SENTINEL)
    text = _DROPPED.sub(" ", text)

    # Unwrap repeatedly: \textbf{\gls{pcr}} needs two passes.
    for _ in range(3):
        text, n = _UNWRAPPED.subn(r"\1", text)
        if not n:
            break

    # Any surviving macro becomes a space. A space, never an empty string:
    # "is \textbf{very} fast" must not collapse to "isvery fast".
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    text = re.sub(r"\\.", " ", text)

    # Math and grouping delimiters are noise once the content is exposed.
    # The non-breaking space ~ is a space.
    text = text.translate(str.maketrans({"$": " ", "~": " ", "{": " ", "}": " "}))

    text = text.replace(_PERCENT_SENTINEL, "%")
    return " ".join(text.split())
