"""Manuscript -> citation sites, each with the claim it is attached to.

The claim window is the text from the previous sentence boundary up to the
\\cite. That is a heuristic, and it is the right one: a citation supports the
assertion it terminates, not the paragraph around it. Widening the window
would pull in quantities the citation was never responsible for and
manufacture false findings.
"""

import re
from pathlib import Path

from sextant.audit.detex import detex
from sextant.audit.models import CitationSite

_CITE = re.compile(r"\\cite[tp]?\*?\s*(?:\[[^\]]*\])*\s*\{([^}]*)\}")
_INPUT = re.compile(r"\\(?:input|include)\s*\{([^}]*)\}")

# A comment starts at an unescaped %. The negative lookbehind is what keeps
# "20\% gain" from truncating the line.
_COMMENT = re.compile(r"(?<!\\)%.*$", re.M)

#: What may stand between two \cite commands that cite one claim together.
_JOINED = re.compile(r"[\s,;~]*")

# Sentence end: . ! or ? followed by whitespace. Also treat a paragraph break
# as a boundary. The start of the document is the fallback.
_BOUNDARY = re.compile(r"(?<=[.!?])\s|\n\s*\n")


def strip_comments(text: str) -> str:
    return _COMMENT.sub("", text)


def citation_sites(text: str, source: str = "") -> list[CitationSite]:
    """Every \\cite in `text`, with its preceding sentence as the claim."""
    body = strip_comments(text)
    sites: list[CitationSite] = []

    previous_end = 0
    for match in _CITE.finditer(body):
        start = 0
        for boundary in _BOUNDARY.finditer(body, 0, match.start()):
            start = boundary.end()
        between = body[previous_end:match.start()]
        # Nor past an earlier \cite in the same sentence. In "20 ms \cite{a}
        # while 5 Gbps \cite{b}", b was checked for a's 20 ms as well.
        start = max(start, previous_end)
        previous_end = match.end()

        keys = tuple(k.strip() for k in match.group(1).split(",") if k.strip())
        if not keys:
            continue

        # "\cite{a}, \cite{b}" is \cite{a,b} written twice: one claim, cited
        # jointly. Kept apart, b got the claim "," and a was faulted for the
        # figure b gave.
        if sites and _JOINED.fullmatch(between):
            last = sites[-1]
            sites[-1] = CitationSite(keys=last.keys + keys, claim=last.claim,
                                     source=last.source, line=last.line)
            continue

        sites.append(
            CitationSite(
                keys=keys,
                claim=detex(body[start : match.start()]).strip(),
                source=source,
                line=body.count("\n", 0, match.start()) + 1,
            )
        )

    return sites


def citation_sites_from_file(
    path: Path | str, _seen: set[Path] | None = None
) -> list[CitationSite]:
    """Sites in `path` and in every file it \\inputs, depth-first."""
    path = Path(path).resolve()
    seen = _seen if _seen is not None else set()
    if path in seen:
        return []
    seen.add(path)

    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return []

    sites = citation_sites(text, source=path.name)

    for match in _INPUT.finditer(strip_comments(text)):
        target = match.group(1).strip()
        child = path.parent / target
        if not child.suffix:
            child = child.with_suffix(".tex")
        sites.extend(citation_sites_from_file(child, seen))

    return sites
