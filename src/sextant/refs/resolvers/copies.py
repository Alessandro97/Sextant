"""Getting a PDF from the places that say they have one.

A source lists several copies of a work: the publisher's, a repository's, a
preprint. The first is often a publisher link that answers scripts with an
HTML page, and the open copies listed after it would never be tried. So every copy is tried in turn, the best version first,
and a file is kept only when it shows the work that was cited -- filing the
wrong paper is worse than filing none.
"""

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from sextant.refs.folder import key_pdf
from sextant.refs.http import Fetcher, Unavailable
from sextant.refs.inbox import first_page_text, shows_work
from sextant.refs.models import BibEntry

#: The most copies tried for one work. A record can list hundreds of URLs,
#: and each that does not answer costs a connect timeout.
MAX_COPIES = 8

#: How far into a file the cited work must show itself. A repository puts a
#: cover sheet in front of the article, sometimes two.
LEADING_PAGES = 3

#: The version vocabulary OpenAlex and Unpaywall share. The published version
#: is what the manuscript cites, page numbers and all; a preprint can differ
#: in exactly the figures a citation is checked against.
_RANK = {"publishedVersion": 0, "acceptedVersion": 1, None: 1, "submittedVersion": 2}

#: A notice about a work reprints its title. OpenAlex can list an erratum as
#: a journal paper's PDF, and the title check alone would have filed it.
#: Only where a line begins: "the fungicide was withdrawn" in an abstract is
#: not a notice, and refused a real paper from every source.
_NOTICE = re.compile(r"(?im)^\W*(erratum|errata|corrigendum|correction to|retraction|"
                     r"retracted|expression of concern|withdrawn|comment on|reply to|"
                     r"response to|addendum)\b")
#: How far into the first page a notice announces itself.
_NOTICE_WINDOW = 300


@dataclass(frozen=True, slots=True)
class Copy:
    url: str
    version: str | None = None
    source: str = ""
    #: The source listed it under the work's DOI, rather than finding it by a
    #: title search. Only such a copy may be kept when it has no text to check.
    keyed_by_doi: bool = True

    @property
    def is_preprint(self) -> bool:
        return self.version == "submittedVersion"


@dataclass(frozen=True, slots=True)
class Fetched:
    path: Path
    copy: Copy


def fetch_first(
    entry: BibEntry,
    copies: Iterable[Copy],
    fetcher: Fetcher,
    dest_dir: Path,
    doi: str | None = None,
) -> tuple[Fetched | None, list[str], bool]:
    """The first copy that downloads and shows the work, notes on the rest,
    and whether a host that did not answer means a retry may yet find it."""
    dest = key_pdf(dest_dir, entry.key)
    notes: list[str] = []
    retry = False
    seen: set[str] = set()
    unique = [c for c in copies if not (c.url in seen or seen.add(c.url))]
    if entry.doi_is_preprint:
        # Whatever a source labels it, a copy of a preprint is a preprint.
        unique = [replace(c, version="submittedVersion") for c in unique]
    ranked = sorted(unique, key=lambda c: _RANK.get(c.version, 1))
    for copy in ranked[:MAX_COPIES]:
        host = urlsplit(copy.url).hostname
        try:
            downloaded = fetcher.download(copy.url, dest)
        except Unavailable as exc:
            notes.append(f"the copy at {host} did not answer ({exc}), try again later")
            retry = True
            continue
        if not downloaded:
            notes.append(f"the copy at {host} would not download")
            continue
        problem = _problem(dest, entry, doi or entry.doi,
                           copy.keyed_by_doi and not entry.doi_found)
        if problem is None:
            return Fetched(dest, copy), notes, retry
        dest.unlink(missing_ok=True)
        notes.append(f"the copy at {host} {problem}")
    return None, notes, retry


def _problem(path: Path, entry: BibEntry, doi: str | None, keyed_by_doi: bool) -> str | None:
    """Why the file at `path` is not the cited work, or None if it is."""
    text = first_page_text(path, pages=LEADING_PAGES)
    if not text.strip():
        return None if keyed_by_doi else "has no text to confirm it by"
    notice = _NOTICE.search(text[:_NOTICE_WINDOW])
    if notice and not re.search(re.escape(notice.group(1)), entry.title or "", re.I):
        return f"is a notice about the work ({notice.group(1).lower()}), not the work"
    # The title may follow a cover sheet; the DOI must be the paper's own, on
    # its first page -- a different paper cites it in its references.
    if not (shows_work(text, entry.key, entry.title, None)
            or shows_work(first_page_text(path), entry.key, None, doi)):
        return "does not show this title or DOI on its first pages"
    return None


def version_note(copy: Copy) -> str:
    """What the reader should know about the copy that was filed in place of
    the one cited: a preprint can differ in exactly the figures a citation is
    checked against."""
    where = f" from {copy.source}" if copy.source else ""
    if copy.version == "submittedVersion":
        return (f"preprint{where}: the published version may differ in pages, "
                "figures and numbers")
    if copy.version == "acceptedVersion":
        return f"accepted manuscript{where}: page numbers differ from the published version"
    return ""
