"""OpenAlex: metadata, open-access locations, and title-to-DOI search.

Since February 2026 OpenAlex ignores mailto and meters by API key. Without
one a reader gets $0.10 a day: lookups by DOI are free, a search costs a
tenth of a cent (https://help.openalex.org/access/example-costs/). So DOIs are
found elsewhere first, and a search here is the last resort. A free key, set
as SEXTANT_OPENALEX_KEY, raises the allowance tenfold.
"""

import os
from pathlib import Path
from urllib.parse import quote, urlencode

from sextant.refs.http import Fetcher
from sextant.refs.linkcheck import normalize_doi
from sextant.refs.models import BibEntry, Resolution
from sextant.refs.titles import titles_match
from sextant.refs.resolvers.copies import Copy, fetch_first, version_note
from sextant.refs.resolvers.doi import different_work, doi_names_entry

BASE = "https://api.openalex.org/works"
KEY = os.environ.get("SEXTANT_OPENALEX_KEY", "")


def work_url(doi: str, key: str = "") -> str:
    url = f"{BASE}/doi:{quote(doi, safe='/')}"
    return f"{url}?{urlencode({'api_key': key})}" if key else url


def _title_filter(title: str) -> str:
    # Filters are separated by commas, so one inside a title split the filter
    # in two and the search failed.
    return f"title.search:{title.replace(',', ' ')}"


class OpenAlexResolver:
    name = "openalex"

    def __init__(self, key: str | None = None) -> None:
        self._key = KEY if key is None else key

    def work_url(self, doi: str) -> str:
        return work_url(doi, self._key)

    def search_url(self, title: str) -> str:
        query = {"filter": _title_filter(title), "per-page": "1"}
        if self._key:
            query["api_key"] = self._key
        return f"{BASE}?{urlencode(query)}"

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution:
        doi = normalize_doi(entry.doi)
        work = None

        if doi:
            work = fetcher.json(self.work_url(doi))
        elif entry.title:
            work = self._search(entry.title, fetcher)

        if not work:
            return Resolution(key=entry.key, status="unresolved",
                              reason="not found in openalex")

        found_doi = normalize_doi(work.get("doi")) or doi
        title = work.get("title")
        if doi and not doi_names_entry(entry, title):
            return different_work(entry, doi, title)

        # is_oa is NOT sufficient. Measured live: a work can report is_oa
        # true, oa_status green, and every location pdf_url null. Only a
        # location's own pdf_url is a copy.
        # Preprints are merged in as further locations: "the arXiv preprint,
        # the journal article, and the repository manuscript are three
        # locations of one work" (https://help.openalex.org/data/locations/).
        copies, landing = copies_of(work, keyed_by_doi=bool(doi))
        # A preprint waits for the preprint step, after PMC and Unpaywall have
        # been asked for the published version.
        copies = [c for c in copies if not c.is_preprint]
        got, notes, retry = fetch_first(entry, copies, fetcher, dest_dir, doi=found_doi)

        if got:
            return Resolution(key=entry.key, status="resolved", doi=found_doi,
                              title=title, pdf_path=str(got.path), version=got.copy.version,
                              reason=version_note(got.copy),
                              resolver=self.name, landing_pages=tuple(landing))

        return Resolution(
            key=entry.key,
            status="no-pdf" if landing else "unresolved",
            reason="; ".join(notes) or ("no listed PDF would download" if copies
                                        else "no location lists a PDF"),
            doi=found_doi,
            title=title,
            landing_pages=tuple(landing),
            retry=retry,
        )

    def _search(self, title: str, fetcher: Fetcher) -> dict | None:
        payload = fetcher.json(self.search_url(title))
        results = (payload or {}).get("results") or []
        if not results:
            return None
        # Never accept a search hit for a different paper.
        return results[0] if titles_match(title, results[0].get("title")) else None


def copies_of(work: dict, keyed_by_doi: bool = True) -> tuple[list[Copy], list[str]]:
    """Every downloadable copy a work lists, and every page a human could open."""
    copies: list[Copy] = []
    landing: list[str] = []
    for location in work.get("locations") or []:
        source = ((location.get("source") or {}).get("display_name")) or ""
        if location.get("pdf_url"):
            copies.append(Copy(location["pdf_url"], version=location.get("version"),
                               source=source, keyed_by_doi=keyed_by_doi))
        page = location.get("landing_page_url")
        if page and page not in landing:
            landing.append(page)
    return copies, landing
