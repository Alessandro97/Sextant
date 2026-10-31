"""Whether the DOI an entry gives is the paper the entry describes.

linkcheck exists because a wrong DOI is common, silent, and caught by nothing
else in a LaTeX workflow. The resolvers that look a DOI up trusted it all the
same: an entry with another paper's DOI was handed that paper's PDF, and that
paper's title. So before anything is downloaded the title the DOI comes back
with is checked against the entry's, the same way linkcheck checks it.
"""

from sextant.refs.models import BibEntry, Resolution
from sextant.refs.titles import titles_overlap


def doi_names_entry(entry: BibEntry, found_title: str | None) -> bool:
    """False only when both titles are known and they name different works."""
    if not entry.title or not found_title:
        return True
    return titles_overlap(entry.title, found_title)


def different_work(entry: BibEntry, doi: str, found_title: str | None) -> Resolution:
    where = "found for this title" if entry.doi_found else "in the .bib"
    return Resolution(
        key=entry.key, status="unresolved", doi=doi, wrong_doi=True,
        reason=f"the DOI {where} names a different work: {found_title}")
