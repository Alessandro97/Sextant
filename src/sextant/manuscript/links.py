"""Compiled manuscript PDF -> citation markers.

LaTeX's hyperref writes a named-destination link on every \\cite marker whose
name is "cite.<bibtex key>" and whose rectangle covers the rendered "[N]".
Reading those is exact: no text parsing, and no guessing which "[3]" is a
citation and which is an equation label.

Measured 2026-08-06 on a real manuscript: 45 citation links across 10
pages, every one yielding a key, a marker string, and a rectangle.

A citation's claim is the whole sentence it appears in, full stop to full
stop, wherever in that sentence the marker happens to sit. Three earlier
attempts took the text before the marker and then patched around the
consequences -- a floor to stop claims accumulating, a trim to the last
sentence boundary, a forward tail that had to stop at the next citation. All
of it existed to approximate "the sentence", which is simply what to take.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from sextant.chat.tidy import tidy
from sextant.index.extract import extract_pages
from sextant.models import Page, Rect

#: A sentence ends at . ! or ? followed by whitespace or the end of the page.
#:
#: A numbered display equation ends one too, and its tag -- "(14)" -- is the
#: only mark of where. The equation itself carries no terminal punctuation, so
#: the prose before one fused to the prose after it:
#:
#:     The queuing delay adds the wait in the input buffer to the wait at the
#:     output port: Tq = W Q + L R + ... , (14) Finally, Tc covers the time
#:     spent checking each packet [21], [23].
#:
#: went to the model as one claim. Retrieval keyed on the queuing vocabulary
#: and returned clauses on buffer occupancy, so the citation was judged
#: against a sentence it was never offered for.
#:
#: Only when a capital follows. That is what separates an equation's tag from
#: a reference to one: "(14) Finally," ends a sentence, while "Eqs. (1) and
#: (2) respectively" and "(13) where x and y are" continue theirs.
_SENTENCE_STOP = re.compile(r"[.!?](?=\s|$)|\(\d{1,3}[a-z]?\)(?=\s+[A-Z])")

#: Citation labels inside a sentence. They are labels, not words, and would
#: otherwise enter the retrieval query as though they meant something.
_MARKERS_IN_TEXT = re.compile(r"\[\d{1,3}(?:\s*[,–—-]\s*\d{1,3})*\]")

#: Punctuation orphaned by removing a marker: "conditions [4], the arrays"
#: leaves " , ", and a sentence ending "[24], [25]." leaves " , .".
_ORPHANED = re.compile(r"\s+([,;:.!?])")
_DOUBLED = re.compile(r"([,;:])(\s*[,;:])+")
#: "at the server [24], [25]." leaves a comma against the full stop.
_DANGLING = re.compile(r"[,;:]+(\s*[.!?])")

#: A page whose text layer carries no punctuation must not yield the whole
#: page as one sentence.
MAX_SENTENCE = 420

#: Retained because other modules import them; the sentence is the unit now.
CLAIM_WINDOW = MAX_SENTENCE
MIN_CLAIM = 12


class NoCitationLinksError(Exception):
    """The PDF carries no cite.* link annotations.

    Almost always means the document was compiled without hyperref, or is not
    the compiled output of a LaTeX manuscript at all.
    """


@dataclass(frozen=True, slots=True)
class CitationMarker:
    """One rendered "[N]" and everything known about it."""

    key: str
    marker: str
    page: int
    rect: Rect
    #: The whole sentence the citation appears in.
    claim: str
    #: The same sentence. Kept as a separate field because callers distinguish
    #: what a citation may be credited for from what it may be faulted for,
    #: and a wider context may return here later.
    context: str = ""
    #: Markers in one sentence share a group. They support that sentence
    #: jointly, so none of them may be faulted alone for it.
    group: int = 0


def _marker_label(raw: str) -> str:
    """The marker as printed: "[4]", not "[4]," or "[4].".

    get_textbox returns everything intersecting the rectangle, and punctuation
    sits tight against a citation often enough to come along with it.
    """
    text = " ".join((raw or "").split())
    found = re.search(r"\[[^\]]{1,12}\]|\d{1,3}", text)
    return found.group(0) if found else (text.strip(".,;:") or "[?]")


#: Abbreviations whose full stop is part of the word. Academic prose is full
#: of them, and each one was ending a sentence early: "computed following
#: Eqs. (1) and (2) respectively [7]" gave the citation a claim of
#: "(1) and (2) respectively", which says nothing and retrieves nothing.
_ABBREVIATIONS = frozenset(
    "eq eqs fig figs sec secs ref refs al vs cf approx tab ch pp vol no resp "
    "eg ie etc et dr prof inc dept fifo".split()
)

#: The word carrying the full stop, dots and all, so "e.g." arrives whole
#: rather than as "g".
_WORD_BEFORE = re.compile(r"([A-Za-z][A-Za-z.]*)\.$")


def _is_boundary(text: str, match: "re.Match[str]") -> bool:
    """False when this full stop belongs to an abbreviation or an initial."""
    if match.group(0).startswith("("):
        return True  # an equation tag, which always ends its sentence
    found = _WORD_BEFORE.search(text[: match.end()])
    if not found:
        return True
    word = found.group(1).replace(".", "").lower()
    # A lone letter is an initial -- "J. Smith", "N. Cassiau".
    return len(word) > 1 and word not in _ABBREVIATIONS


def sentence_bounds(page: Page, offset: int) -> tuple[int, int]:
    """The character range of the sentence containing `offset`."""
    text = page.text
    offset = max(0, min(offset, len(text)))

    start = 0
    for stop in _SENTENCE_STOP.finditer(text, 0, offset):
        if _is_boundary(text, stop):
            start = stop.end()
    while start < len(text) and text[start].isspace():
        start += 1

    end = len(text)
    for found in _SENTENCE_STOP.finditer(text, offset):
        if _is_boundary(text, found):
            end = found.end()
            break

    if end - start > MAX_SENTENCE:
        # Keep the marker in the middle, but never cut inside a word: the
        # clamp landed mid-token and handed the model "uency, the ratio over
        # interval B is", which reads as a different claim than the one made.
        start = _snap_forward(text, max(start, offset - MAX_SENTENCE // 2))
        end = _snap_back(text, min(end, offset + MAX_SENTENCE // 2))
    return (start, min(end, len(text)))


def _snap_forward(text: str, position: int) -> int:
    """The start of the first whole word at or after `position`."""
    if position <= 0 or text[position - 1].isspace():
        return position
    while position < len(text) and not text[position].isspace():
        position += 1
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _snap_back(text: str, position: int) -> int:
    """The end of the last whole word at or before `position`."""
    if position >= len(text) or text[position].isspace():
        return position
    while position > 0 and not text[position - 1].isspace():
        position -= 1
    return position


def _without_markers(text: str) -> str:
    """Drop citation labels and the punctuation they leave stranded."""
    stripped = _MARKERS_IN_TEXT.sub(" ", text)
    stripped = _DOUBLED.sub(r"\1", stripped)
    stripped = _DANGLING.sub(r"\1", stripped)
    stripped = _ORPHANED.sub(r"\1", stripped)
    return tidy(stripped)


def sentence_at(page: Page | None, offset: int) -> tuple[str, int]:
    """(the sentence containing `offset`, the offset it begins at).

    The marker sitting inside it is removed along with any others: a citation
    is placed in a sentence, it is not part of what the sentence says.
    """
    if page is None:
        return ("", 0)
    start, end = sentence_bounds(page, offset)
    return (_without_markers(page.text[start:end]), start)


def sentence_with_lead_in(page: Page | None, offset: int) -> str:
    """The sentence containing `offset`, and the one before it.

    Used for credit, never for blame. A paper is often cited a sentence after
    the figures it supplies -- "the sensor drift is 1.1 dB/K in the cold room. These
    values apply to the reference unit only [4]" -- and looking only at the citation's
    own sentence lost a verification that was correct. Faulting still uses the
    sentence alone: being unsupported is a much stronger claim.
    """
    if page is None:
        return ""
    start, end = sentence_bounds(page, offset)
    lead_in = start
    if start > 0:
        lead_in = sentence_bounds(page, max(0, start - 2))[0]
    return _without_markers(page.text[lead_in:end])


def assemble(placed, by_number: dict[int, Page]) -> list[CitationMarker]:
    """Turn located markers into citations, one sentence each.

    Shared by all three backends: how a marker is found differs between
    hyperref, superscripts and brackets; what a claim is does not.

    `placed` is (page number, key, marker text, rect, character offset), in
    reading order.
    """
    markers: list[CitationMarker] = []
    groups: dict[tuple[int, int], int] = {}

    for page_number, key, marker_text, rect, offset in placed:
        page = by_number.get(page_number)
        claim, start = sentence_at(page, offset)
        # Two markers in one sentence are one joint citation of it.
        group = groups.setdefault((page_number, start), len(groups) + 1)

        markers.append(
            CitationMarker(
                key=key,
                marker=marker_text,
                page=page_number,
                rect=rect,
                claim=claim,
                context=sentence_with_lead_in(page, offset),
                group=group,
            )
        )
    return markers


def citation_markers(pdf_path: Path | str) -> list[CitationMarker]:
    """Every citation marker in the compiled manuscript, in reading order."""
    pages = extract_pages(pdf_path)
    by_number = {page.number: page for page in pages}

    doc = pymupdf.open(pdf_path)
    try:
        raw: list[tuple[int, str, pymupdf.Rect, str]] = []
        for pdf_page in doc:
            for link in pdf_page.get_links():
                name = str(link.get("nameddest") or link.get("name") or "")
                if not name.startswith("cite."):
                    continue
                rect = link["from"]
                raw.append(
                    (
                        pdf_page.number + 1,
                        name[len("cite.") :],
                        rect,
                        _marker_label(pdf_page.get_textbox(rect)),
                    )
                )
    finally:
        doc.close()

    if not raw:
        # No link annotations. A Word manuscript in Vancouver or AMA style puts
        # the citation in a superscript run, which PyMuPDF flags; failing that
        # there is "[12]" in the body text, accepted only for numbers the
        # reference list defines.
        from sextant.manuscript.bibliography import (bracketed_bibliography,
                                                     numbered_bibliography)
        from sextant.manuscript.bracketed import bracketed_markers
        from sextant.manuscript.superscript import superscript_markers

        # Both, and whichever finds more. Taking superscripts whenever there
        # were any let one exponent -- the 2 of km² -- stand in for every
        # bracketed citation in the paper.
        superscripts = superscript_markers(
            pdf_path, known=set(numbered_bibliography(pdf_path)))
        bracketed = bracketed_markers(pdf_path, set(bracketed_bibliography(pdf_path)))
        markers = max(superscripts, bracketed, key=len)
        if markers:
            return markers

        raise NoCitationLinksError(
            f"{pdf_path} has no citation markers Sextant can read. It needs "
            "either a LaTeX PDF compiled with hyperref, or superscript "
            "citation numbers as Word produces for Vancouver and AMA styles."
        )

    # Locate each marker by the word it overlaps, which puts it at an exact
    # character offset in reading order. Sorting on geometry instead would
    # interleave the columns of a two-column paper.
    located = [
        (page_number, key, rect, text,
         _marker_offset(by_number.get(page_number), rect)[0])
        for page_number, key, rect, text in raw
    ]
    located.sort(key=lambda item: (item[0], item[4], item[2].x0))

    return assemble(
        [
            (page_number, key, marker_text,
             Rect(rect.x0, rect.y0, rect.x1, rect.y1), offset)
            for page_number, key, rect, marker_text, offset in located
        ],
        by_number,
    )


def _marker_offset(page: Page | None, rect: "pymupdf.Rect") -> tuple[int, int]:
    """(start, end) in page.text of the word the marker sits on.

    page.words is in reading order with exact offsets, so overlapping the link
    rectangle against it gives the marker's true position in the prose --
    correct across column breaks, where geometry alone is not.
    """
    if page is None:
        return (0, 0)

    best, best_overlap = (0, 0), 0.0
    for word in page.words:
        overlap_x = min(word.rect.x1, rect.x1) - max(word.rect.x0, rect.x0)
        overlap_y = min(word.rect.y1, rect.y1) - max(word.rect.y0, rect.y0)
        if overlap_x <= 0 or overlap_y <= 0:
            continue
        area = overlap_x * overlap_y
        if area > best_overlap:
            best, best_overlap = (word.start, word.end), area

    if best_overlap:
        return best

    # No word under the rectangle: fall back to the last word that both starts
    # left of it and sits no lower on the page.
    end = 0
    for word in page.words:
        centre_y = (word.rect.y0 + word.rect.y1) / 2
        if word.rect.x1 <= rect.x1 + 2.0 and centre_y <= rect.y1 + 3.0:
            end = max(end, word.end)
    return (end, end)
