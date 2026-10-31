"""Adopt PDFs a human dropped into refs/inbox/.

No renaming required: the title and DOI are read from the dropped file's own
first page and matched against pending references.

An ambiguous or unrecognised file is REPORTED, never guessed. Filing a paper
under the wrong citation key would produce a confident verdict about the wrong
document — the same class of error as a wrong highlight, and equally
unacceptable.
"""

import re
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import pymupdf

from sextant.refs.linkcheck import normalize_doi
from sextant.refs.models import Resolution
from sextant.refs.titles import title_on_page

_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")

#: A 3GPP specification number in the form only its own cover gives it,
#: with its version: "3GPP TS 23.501 V19.4.0". A paper's abstract mentioning
#: "the architecture in TS 23.501" would otherwise be filed as TS 23.501.
_SPEC_COVER = re.compile(r"\bT[RS]\s+(\d{2})\.(\d{3})\s+V\d+\.\d+\.\d+")
#: The same number inside a bibtex key: 3gpp_ts_23501, or bare 21905.
_SPEC_IN_KEY = re.compile(r"(?<!\d)(\d{2})(\d{3})(?!\d)")


def cover_spec_numbers(text: str) -> set[str]:
    """The specifications `text` is the cover of, rather than merely mentions."""
    return {f"{a}.{b}" for a, b in _SPEC_COVER.findall(text)}


def spec_from_key(key: str) -> str | None:
    """The specification a bibtex key names, if it names one.

    For a standard the number is the identity and the title is not: a
    manuscript citing "TS 23.501 (Release 15)" and a download of Release 19
    have titles that differ only in that parenthesis, so title matching fails
    in both directions while the number matches exactly.
    """
    found = _SPEC_IN_KEY.findall(key or "")
    return f"{found[0][0]}.{found[0][1]}" if len(found) == 1 else None


def first_page_text(path: Path, pages: int = 1) -> str:
    """First page text, prefixed with the PDF's own title metadata.

    Publishers usually set /Title, and when they do it is the cleanest signal
    available -- no masthead, no running head, no abstract in the way. It
    costs nothing to look, and the page text still follows for the many files
    where the field is empty or junk.
    """
    try:
        doc = pymupdf.open(path)
    except Exception:
        return ""
    try:
        meta = (doc.metadata or {}).get("title") or ""
        page = "\n".join(doc[n].get_text() for n in range(min(pages, doc.page_count)))
        return f"{meta}\n{page}" if meta.strip() else page
    except Exception:
        return ""
    finally:
        doc.close()


def adopt(inbox: Path, pending: Sequence[Resolution]) -> list[Resolution]:
    """Match dropped PDFs to pending references. Returns those newly resolved."""
    if not inbox.is_dir():
        return []

    adopted: list[Resolution] = []
    claimed: set[str] = set()

    for dropped in sorted(inbox.glob("*.pdf")):
        text = first_page_text(dropped)
        if not text.strip():
            continue

        candidates = [
            r for r in pending
            if r.key not in claimed and _matches(text, r)
        ]

        # Exactly one, or nothing. Never a best guess.
        if len(candidates) != 1:
            continue

        target = candidates[0]
        claimed.add(target.key)
        adopted.append(
            replace(
                target,
                status="resolved",
                reason="adopted from inbox",
                pdf_path=str(dropped.resolve()),
                resolver="inbox",
            )
        )

    return adopted


def _matches(text: str, resolution: Resolution) -> bool:
    return shows_work(text, resolution.key, resolution.title, resolution.doi)


def shows_work(text: str, key: str, title: str | None, doi: str | None) -> bool:
    """Does a file whose leading text is `text` look like the cited work?

    The title is searched across the WHOLE first page, not a leading window.
    A magazine can open with a masthead, an ISSN, a page number and the
    abstract callout before the title, which then begins well past the
    hundredth word: a fixed leading window misses it entirely and the paper is
    silently not adopted. It must stand on its own lines, though, not merely
    appear: see title_on_page.
    """
    wanted_doi = normalize_doi(doi)
    if wanted_doi:
        for found in _DOI.findall(text):
            if found.rstrip(".,;").lower() == wanted_doi.lower():
                return True

    wanted_spec = spec_from_key(key)
    if wanted_spec and wanted_spec in cover_spec_numbers(text):
        return True

    return title_on_page(title, text)
