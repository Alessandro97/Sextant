"""Does the entry's DOI resolve to the work the entry claims?

Copy-pasted bib entries with the wrong DOI are silent, common, and caught by
nothing else in a normal LaTeX workflow. This is the cheapest real check in
the whole system: metadata only, no PDFs, no model.

Precision matters more than recall here. A checker that cries wolf gets
ignored, so a mismatch is reported only when the titles genuinely differ, not
when two copies of one title are merely written differently.
"""

from urllib.parse import quote

from sextant.refs.http import Fetcher
from sextant.refs.models import BibEntry, LinkCheck
from sextant.refs.titles import titles_overlap

CROSSREF = "https://api.crossref.org/works/"


def normalize_doi(raw: str | None) -> str | None:
    """Strip whitespace and any doi.org prefix. Returns None if unusable."""
    if not raw:
        return None
    doi = raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
    doi = doi.strip()
    return doi or None


def check_entry(entry: BibEntry, fetcher: Fetcher) -> LinkCheck:
    doi = normalize_doi(entry.doi)
    if doi is None:
        return LinkCheck(key=entry.key, verdict="no-doi", claimed=entry.title)

    if not entry.title:
        return LinkCheck(key=entry.key, verdict="no-title")

    payload = fetcher.json(CROSSREF + quote(doi, safe="/"))
    if not payload:
        return LinkCheck(key=entry.key, verdict="unresolved", claimed=entry.title)

    titles = (payload.get("message") or {}).get("title") or []
    actual = titles[0] if titles else None
    if not actual:
        return LinkCheck(key=entry.key, verdict="unresolved", claimed=entry.title)

    verdict = "match" if titles_overlap(entry.title, actual) else "mismatch"
    return LinkCheck(key=entry.key, verdict=verdict, claimed=entry.title, actual=actual)
