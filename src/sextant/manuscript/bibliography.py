"""Read the reference list out of a compiled manuscript.

With only a PDF in hand there is no .bib, so titles and DOIs have to come from
the document's own bibliography. hyperref marks where each `cite.<key>` link
LANDS -- that destination is the reference entry itself -- which tells us which
pages hold the reference list without guessing at headings.

Entries are then split on their "[N]" labels and matched back to keys through
the marker mapping the citation links already gave us. That avoids parsing
author names or trusting entry order.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from sextant.manuscript.links import citation_markers

_LABEL = re.compile(r"\[(\d{1,3})\]")
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
#: IEEE style puts the title in curly or straight quotes after the authors.
_TITLE = re.compile(r"[“\"']([^”\"']{12,300})[”\"']")


@dataclass(frozen=True, slots=True)
class BibEntryFromPdf:
    key: str
    label: str
    raw: str
    title: str | None = None
    doi: str | None = None


def _reference_pages(doc: "pymupdf.Document") -> list[int]:
    """0-indexed pages the cite.* destinations land on: the reference list."""
    pages = {
        d["page"]
        for name, d in doc.resolve_names().items()
        if name.startswith("cite.") and "page" in d
    }
    return sorted(pages)


def bibliography(pdf_path: Path | str) -> dict[str, BibEntryFromPdf]:
    """Reference entries keyed by bibtex key, read from the PDF itself."""
    markers = citation_markers(pdf_path)
    key_for_label = {m.marker.strip("[]"): m.key for m in markers}
    if not key_for_label:
        return {}

    doc = pymupdf.open(pdf_path)
    try:
        pages = _reference_pages(doc)
        if not pages:
            return {}
        text = " ".join(" ".join(doc[n].get_text().split()) for n in pages)
    finally:
        doc.close()

    # Split on the "[N]" labels. Everything before the first one is body text
    # that shared a page with the reference list.
    hits = list(_LABEL.finditer(text))
    entries: dict[str, BibEntryFromPdf] = {}
    for index, hit in enumerate(hits):
        label = hit.group(1)
        key = key_for_label.get(label)
        if key is None or key in entries:
            continue
        end = hits[index + 1].start() if index + 1 < len(hits) else len(text)
        raw = text[hit.end() : end].strip()
        if not raw:
            continue
        entries[key] = BibEntryFromPdf(
            key=key,
            label=f"[{label}]",
            raw=raw,
            title=_extract_title(raw),
            doi=(_DOI.search(raw).group(0).rstrip(".") if _DOI.search(raw) else None),
        )
    return entries


def _extract_title(raw: str) -> str | None:
    match = _TITLE.search(raw)
    if match:
        return " ".join(match.group(1).split()).rstrip(",.")
    # No quotes: books and standards. Take the span after the first comma,
    # which is where the authors end in IEEE style.
    _, _, rest = raw.partition(",")
    candidate = " ".join(rest.split()).split(".")[0]
    return candidate.strip() or None


def entries_for(pdf_path: Path | str) -> dict[str, BibEntryFromPdf]:
    """The reference list, however this manuscript records it."""
    for reader in (bibliography, labelled_bibliography, numbered_bibliography):
        found = reader(pdf_path)
        if found:
            return found
    return {}


def as_bib_entries(pdf_path: Path | str) -> dict:
    """PDF-derived references shaped like parsed .bib entries.

    Lets the resolver chain run against an uploaded PDF that arrived with no
    bibliography file. Measured on a real manuscript: 28 of 28 titles
    recovered, which is what OpenAlex title search needs.
    """
    from sextant.refs.models import BibEntry

    return {
        key: BibEntry(
            key=key,
            entry_type="article",
            title=entry.title,
            doi=entry.doi,
        )
        for key, entry in entries_for(pdf_path).items()
        if entry.title or entry.doi
    }


#: A Vancouver reference-list label: "12. Author AB, ..."
#:
#: The lookahead admits "[" as well as a letter. Entry 15 of a real proposal
#: reads "15. [Reference for AQP4 mislocalisation -- supply from your own
#: reading]": an unfilled placeholder, and precisely the entry its author most
#: needs to see. Requiring a capital dropped it and every entry after it,
#: turning 28 references into 14.
_NUMBERED = re.compile(r"(?<![\d.])(\d{1,3})\.\s+(?=[A-Za-z\[\u201c\"])")


def numbered_bibliography(pdf_path: Path | str) -> dict[str, BibEntryFromPdf]:
    """Reference entries from a Word-style numbered list.

    "N." is far weaker evidence than a hyperref destination: section headings
    and enumerated aims look identical to a regex. The list is therefore
    identified by its shape rather than its labels -- the longest run of
    labels ascending by exactly one, starting at 1. A section numbered "5."
    in the middle of the prose cannot join such a run without a 4. before it
    and a 6. after it, which is what makes this safe enough to act on.
    """
    doc = pymupdf.open(pdf_path)
    try:
        text = " ".join(" ".join(page.get_text().split()) for page in doc)
    finally:
        doc.close()

    labels = [(int(m.group(1)), m.start(), m.end()) for m in _NUMBERED.finditer(text)]
    if not labels:
        return {}

    # Walk forward taking only the next number in sequence and ignoring
    # anything else. A cross-reference inside an entry -- one really reads
    # "Potter GM, et al. -- see ref. 17." -- is indistinguishable from a label,
    # and resetting on it truncated a 28-entry list at 25.
    # Every "1." is a candidate start; the longest run wins. Stopping at the
    # first one locked onto a numbered list in the body prose ("New training
    # 1 - clinical MS") and read the whole narrative as a bibliography.
    best: list[tuple[int, int, int]] = []
    for start, first in enumerate(labels):
        if first[0] != 1:
            continue
        run = [first]
        for label in labels[start + 1:]:
            if label[0] == run[-1][0] + 1:
                run.append(label)
        if len(run) >= len(best):     # a later run of equal length is the list
            best = run

    # Two entries prove nothing; a bibliography is longer than that.
    if len(best) < 5:
        return {}

    entries: dict[str, BibEntryFromPdf] = {}
    for index, (number, _, end) in enumerate(best):
        stop = best[index + 1][1] if index + 1 < len(best) else len(text)
        raw = text[end:stop].strip()
        if not raw:
            continue
        entries[str(number)] = BibEntryFromPdf(
            key=str(number),
            label=f"[{number}]",
            raw=raw,
            title=_vancouver_title(raw),
            doi=(_DOI.search(raw).group(0).rstrip(".") if _DOI.search(raw) else None),
        )
    return entries


#: An author list: "Smith AB, Jones C, et al" -- surnames with bare initials.
_AUTHORS = re.compile(r"^(?:[A-Z][A-Za-z'\u2019-]+ [A-Z]{1,3}|et al\.?|and)"
                      r"(?:,|$|\s*$)")


#: An institution standing where the authors normally stand. Only ever applied
#: to the first segment, which is the author position -- a body named in a real
#: title sits later, after the authors, and is untouched by this.
_CORPORATE = re.compile(
    r"\b(?:Union|Corporation|Organi[sz]ation|Institute|Institution|Agency|"
    r"Commission|Committee|Consortium|Ministry|Department|Council|Association|"
    r"Foundation|Administration|Bureau|Authority|Partnership Project|Bank|"
    r"Alliance|Forum|Society|Laborator(?:y|ies)|Inc|Ltd|LLC|GmbH|Corp|"
    r"3GPP|ETSI|ITU|ISO|IETF|IETF|NIST|OECD|UNESCO|WHO)\b")


#: "International Finance Corporation (IFC)" -- a body glossing its own
#: initials, which titles do not do.
_ACRONYM = re.compile(r"\([A-Z]{2,6}\)\s*$")


#: Where an entry says how to reach the paper rather than what it is called.
#: These read like sentences and would otherwise be taken for titles.
_LOCATOR = re.compile(r"^(?:Available|Accessed|Retrieved|Cited|Online|In|Presented|"
                      r"doi|DOI|https?|www\.|\[(?:Internet|Online)\])\b[:.]?",
                      re.IGNORECASE)


def _mostly_digits(segment: str) -> bool:
    """A volume-and-pages block: "2020;1(2):3-4", "35(4):255-61".

    Screening on a leading digit instead dropped every title that opens with a
    numeral -- and "19th-Century Grain Ledgers" is the common case in a
    history bibliography, not the exceptional one. The parser skipped
    it and returned the journal name as the title. Counting characters
    separates the two: a title is words, a locator is numbers and punctuation.
    """
    letters = sum(c.isalpha() for c in segment)
    return letters * 2 < len(segment.replace(" ", ""))


def _vancouver_title(raw: str) -> str | None:
    """The title from "Authors. Title. Journal. Year;vol(iss):pages."

    Position cannot be trusted. "Jones C. A Study Of Wetlands." ends its
    author list with an initial, so a split that ignores stops after capitals
    keeps the authors and the title together and returns the journal instead.

    So segments are judged by what they look like: the first one that is not
    an author list and reads like a sentence is the title. Journal names are
    short and abbreviated, which is what the word count screens out.
    """
    # "?" and "!" end a title as surely as a stop does. Splitting on the stop
    # alone ran "Who Pays for Restoration?" straight on into the conference
    # name, proceedings and year that followed it.
    segments = [s.strip() for s in re.split(r"[.?!]\s+", raw) if s.strip()]
    for index, segment in enumerate(segments):
        if index == 0 and len(segments) > 1 and (
                _CORPORATE.search(segment) or _ACRONYM.search(segment)):
            continue          # "International Soil Survey Commission. ..."
        if _AUTHORS.match(segment) or "et al" in segment.lower():
            continue
        if len(segment.split()) < 3:
            continue          # "J Ecol", "Ann Intern Med"
        if _LOCATOR.match(segment):
            continue          # "Available from: 10.5555/...", "Accessed 3 Jan"
        if _mostly_digits(segment):
            continue          # "2020;1(2):3-4"
        # A publication year clings to the title when no stop separates them:
        # "Seed banks to restore degraded grassland across Kenya; 2020".
        return re.sub(r"[;,]\s*(?:19|20)\d{2}\s*$", "", segment).rstrip(".,;")
    return None


#: A reference list heading, used when there are no hyperref destinations to
#: locate the list by.
_LIST_HEADING = re.compile(r"\b(?:REFERENCES|References|BIBLIOGRAPHY|Bibliography)\b")


#: How publishers label a reference list. IEEE and ACM bracket it, Vancouver
#: and Springer use a bare ordinal, some house styles parenthesise. The label
#: is the publisher's business; the run is what identifies the list.
_LABEL_STYLES = (
    ("bracketed",     re.compile(r"\[(\d{1,3})\]")),
    ("parenthesised", re.compile(r"\((\d{1,3})\)\s+(?=[A-Z\u201c\"])")),
    ("ordinal",       re.compile(r"(?<![\d.])(\d{1,3})[.)]\s+(?=[A-Za-z\[\u201c\"])")),
)


def _after_list_heading(text: str) -> str | None:
    """Everything past the last "References" heading, or None.

    The last occurrence is the right one: papers mention the word in prose
    before they reach the list.
    """
    headings = list(_LIST_HEADING.finditer(text))
    return text[headings[-1].end():] if headings else None


def _longest_run(tail: str, pattern: "re.Pattern") -> list[tuple[int, int, int]]:
    """Labels ascending by exactly one from 1 -- the shape of a reference list.

    A section numbered 5 in the prose cannot join such a run without a 4
    before it and a 6 after it. Every 1 is a candidate start and the longest
    run wins, because a short numbered list earlier in the document would
    otherwise capture the search.
    """
    labels = [(int(m.group(1)), m.start(), m.end()) for m in pattern.finditer(tail)]
    best: list[tuple[int, int, int]] = []
    for start, first in enumerate(labels):
        if first[0] != 1:
            continue
        run = [first]
        for label in labels[start + 1:]:
            if label[0] == run[-1][0] + 1:
                run.append(label)
        if len(run) > len(best):
            # Strictly longer, so the earliest start wins a tie. An entry's own
            # text supplies false labels -- "...Reference Number 1. J Ecol" --
            # and a later equal run began there, dropping the entry's title.
            best = run
    return best


def labelled_bibliography(pdf_path: Path | str) -> dict[str, BibEntryFromPdf]:
    """The reference list, whatever the publisher labels it with.

    Tries each label style against the text after the heading and keeps the
    one that yields the longest run. Restricting to the heading first is what
    makes the weaker styles safe: scanning a whole paper for "1." found a run
    of lemmas in the body prose and read six equations as a bibliography.
    """
    doc = pymupdf.open(pdf_path)
    try:
        text = " ".join(" ".join(page.get_text().split()) for page in doc)
    finally:
        doc.close()

    tail = _after_list_heading(text)
    if tail is None:
        return {}

    best_run: list[tuple[int, int, int]] = []
    for _name, pattern in _LABEL_STYLES:
        run = _longest_run(tail, pattern)
        if len(run) > len(best_run):
            best_run = run
    if len(best_run) < 5:
        return {}

    entries: dict[str, BibEntryFromPdf] = {}
    for index, (number, _, end) in enumerate(best_run):
        stop = best_run[index + 1][1] if index + 1 < len(best_run) else len(tail)
        raw = tail[end:stop].strip()
        if not raw:
            continue
        entries[str(number)] = BibEntryFromPdf(
            key=str(number),
            label=f"[{number}]",
            raw=raw,
            title=_vancouver_title(raw) or _extract_title(raw),
            doi=(_DOI.search(raw).group(0).rstrip(".") if _DOI.search(raw) else None),
        )
    return entries


def bracketed_bibliography(pdf_path: Path | str) -> dict[str, BibEntryFromPdf]:
    """Reference entries labelled "[N]", found by their heading.

    bibliography() locates the list through hyperref destinations. Without
    those, the heading is the only landmark -- and the last occurrence is the
    right one, since papers mention the word in prose before they reach it.
    """
    doc = pymupdf.open(pdf_path)
    try:
        text = " ".join(" ".join(page.get_text().split()) for page in doc)
    finally:
        doc.close()

    headings = list(_LIST_HEADING.finditer(text))
    if not headings:
        return {}
    tail = text[headings[-1].end():]

    labels = [(int(m.group(1)), m.start(), m.end())
              for m in re.finditer(r"\[(\d{1,3})\]", tail)]
    run: list[tuple[int, int, int]] = []
    for label in labels:
        if not run and label[0] == 1:
            run.append(label)
        elif run and label[0] == run[-1][0] + 1:
            run.append(label)
    if len(run) < 5:
        return {}

    entries: dict[str, BibEntryFromPdf] = {}
    for index, (number, _, end) in enumerate(run):
        stop = run[index + 1][1] if index + 1 < len(run) else len(tail)
        raw = tail[end:stop].strip()
        if not raw:
            continue
        entries[str(number)] = BibEntryFromPdf(
            key=str(number),
            label=f"[{number}]",
            raw=raw,
            title=_vancouver_title(raw) or _extract_title(raw),
            doi=(_DOI.search(raw).group(0).rstrip(".") if _DOI.search(raw) else None),
        )
    return entries


#: A bibtex key that names its author and year: lopez2022survey,
#: okafor2021dynamics, berg2005pasture. Common enough to be worth a fallback, and
#: never trusted on its own -- see entry_for_citation.
_AUTHOR_YEAR_KEY = re.compile(r"^([A-Za-z][A-Za-z'-]{2,})(\d{4})")


def entry_for_citation(
    key: str, label: str, entries: dict
) -> "BibEntryFromPdf | None":
    """The reference-list entry a citation points at, however the list is keyed.

    A manuscript compiled from LaTeX carries hyperref keys -- 4821377,
    lopez2022survey -- while its printed reference list is numbered. The
    two never met, so a library of thirty-two references showed thirty-two
    opaque keys and no titles.

    Three joins, most certain first:

    1. The key itself, when the list is keyed that way (a .bib).
    2. The printed label, reduced to its digits. "[12]", "12.", "(12)" and a
       superscript 12 all reduce to "12", so the publisher's bracket style
       does not matter.
    3. Author and year taken from the key, matched against the entry text.
       Only when exactly one entry matches: two references by the same author
       in the same year are common, and attaching the wrong one would put a
       title on a citation that is not its own.
    """
    if not entries:
        return None
    if key in entries:
        return entries[key]

    digits = re.sub(r"\D", "", label or "").lstrip("0")
    if digits and digits in entries:
        return entries[digits]

    named = _AUTHOR_YEAR_KEY.match(key or "")
    if named:
        surname, year = named.group(1).lower(), named.group(2)
        hits = [
            entry for entry in entries.values()
            if surname in (entry.raw or "").lower() and year in (entry.raw or "")
        ]
        if len(hits) == 1:
            return hits[0]
    return None
