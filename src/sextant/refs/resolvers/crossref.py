"""Crossref: the DOI for an entry that has none, and publishers' PDF links.

Free and keyless, so it is where a missing DOI is looked for: OpenAlex charges
for a search and not for a lookup by DOI. Every later source in the chain is
handed what is found here.

A record's `link` array is where publishers deposit full-text URLs. Those for
"similarity-checking" exist so that "Turnitin [can] index your content"
(https://www.crossref.org/documentation/schema-library/markup-guide-metadata-segments/full-text-urls/)
and are left alone; the rest are tried, and a URL "does not guarantee
access" -- many need a subscription, and simply fail to download.
"""

from dataclasses import replace
from pathlib import Path
from urllib.parse import quote, urlencode

from sextant.refs.http import CONTACT, Fetcher
from sextant.refs.linkcheck import normalize_doi
from sextant.refs.models import BibEntry, Resolution
from sextant.refs.resolvers.copies import Copy, fetch_first, version_note
from sextant.refs.resolvers.doi import different_work, doi_names_entry
from sextant.refs.titles import titles_match

BASE = "https://api.crossref.org/works"

#: content-version to the version vocabulary the copies are ranked by.
_VERSIONS = {"vor": "publishedVersion", "am": "acceptedVersion"}

#: Record types that share a title with the article they precede or review:
#: working papers and preprints (posted-content, report), peer reviews, and
#: a paper's figures (component). Taken only for an entry of the same kind.
_ASIDE = {"posted-content": {"unpublished", "misc"}, "report": {"techreport"},
          "peer-review": set(), "component": set()}
_PREPRINT_ONLY = "the only work with this title is a preprint or working paper"


def crossref_work_url(doi: str, contact: str = "") -> str:
    url = f"{BASE}/{quote(doi, safe='/')}"
    return f"{url}?{urlencode({'mailto': contact})}" if contact else url


def _year(item: dict) -> int | None:
    for field in ("issued", "published", "published-print", "published-online"):
        parts = (item.get(field) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


class CrossrefResolver:
    name = "crossref"

    def __init__(self, contact: str | None = None) -> None:
        # Crossref's polite pool asks for an address; only the reader's own
        # is ever sent, and only if they set one.
        self._contact = CONTACT if contact is None else contact

    def search_url(self, entry: BibEntry) -> str:
        query = {"query.bibliographic": entry.title or "", "rows": "5"}
        if self._contact:
            query["mailto"] = self._contact
        return f"{BASE}?{urlencode(query)}"

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution:
        doi = normalize_doi(entry.doi)
        found, note = None, ""
        if not doi:
            if not entry.title:
                return Resolution(key=entry.key, status="unresolved",
                                  reason="no doi or title to look up")
            found, note = self._find_doi(entry, fetcher)
            if not found:
                return Resolution(key=entry.key, status="unresolved", reason=note)
            doi = found
            entry = replace(entry, doi=found, doi_found=True,
                            doi_is_preprint=note == _PREPRINT_ONLY)

        payload = fetcher.json(crossref_work_url(doi, self._contact))
        record = (payload or {}).get("message") or {}
        if not record:
            return Resolution(key=entry.key, status="unresolved", doi=found,
                              reason="; ".join(filter(None, [note, "not in crossref"])),
                              doi_is_preprint=entry.doi_is_preprint)
        title = (record.get("title") or [None])[0]
        if not found and not doi_names_entry(entry, title):
            return different_work(entry, doi, title)

        copies = [Copy(link["URL"], version=_VERSIONS.get(link.get("content-version")),
                       source="the publisher")
                  for link in record.get("link") or []
                  if link.get("URL") and link.get("content-type") == "application/pdf"
                  and link.get("intended-application") != "similarity-checking"]
        got, notes, retry = fetch_first(entry, copies, fetcher, dest_dir, doi=doi)
        if got:
            return Resolution(key=entry.key, status="resolved", doi=doi, title=title,
                              pdf_path=str(got.path), version=got.copy.version, resolver=self.name,
                              reason=version_note(got.copy))
        return Resolution(key=entry.key, status="unresolved", doi=found, title=title,
                          reason="; ".join(filter(None, [note if found else "", *notes]))
                          or "no publisher PDF link", retry=retry,
                          doi_is_preprint=entry.doi_is_preprint)

    def _find_doi(self, entry: BibEntry, fetcher: Fetcher) -> tuple[str | None, str]:
        """The DOI of the one work with this title, kind and year, or a reason.

        Crossref ranked a 2011 working paper first for the 2014 article of the
        same title, and a working paper is not the article. Where two works
        remain -- a conference paper and its journal version -- neither is
        taken: guessing between them files the wrong one half the time.
        """
        payload = fetcher.json(self.search_url(entry))
        wanted_year = int(entry.year) if (entry.year or "").isdigit() else None
        found: dict[bool, dict[int, set[str]]] = {False: {}, True: {}}
        for item in ((payload or {}).get("message") or {}).get("items") or []:
            if not titles_match(entry.title, (item.get("title") or [""])[0]):
                continue
            year = _year(item)
            distance = abs(year - wanted_year) if wanted_year and year else 0
            if distance > 1 or not item.get("DOI"):
                continue
            kind = item.get("type")
            aside = kind in _ASIDE and entry.entry_type not in _ASIDE[kind]
            found[aside].setdefault(distance, set()).add(normalize_doi(item["DOI"]))
        # A preprint or working paper only when nothing else has the title:
        # biologists cite bioRxiv preprints as @article, and then it is the work.
        by_distance = found[False] or found[True]
        if not by_distance:
            return None, "no work in crossref with this title and year"
        nearest = by_distance[min(by_distance)]
        if len(nearest) > 1:
            return None, f"several works share this title: {', '.join(sorted(nearest))}"
        if not found[False]:
            return next(iter(nearest)), _PREPRINT_ONLY
        return next(iter(nearest)), ""
