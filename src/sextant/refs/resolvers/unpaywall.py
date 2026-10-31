"""Unpaywall: DOI to an open-access PDF, when one genuinely exists."""

from pathlib import Path
from urllib.parse import quote

from sextant.refs.http import CONTACT, Fetcher
from sextant.refs.linkcheck import normalize_doi
from sextant.refs.models import BibEntry, Resolution
from sextant.refs.resolvers.copies import Copy, fetch_first, version_note
from sextant.refs.resolvers.doi import different_work, doi_names_entry

BASE = "https://api.unpaywall.org/v2/"


def unpaywall_url(doi: str, contact: str) -> str:
    return f"{BASE}{quote(doi, safe='/')}?email={quote(contact)}"


class UnpaywallResolver:
    name = "unpaywall"

    def __init__(self, contact: str | None = None) -> None:
        self._contact = CONTACT if contact is None else contact

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution:
        doi = normalize_doi(entry.doi)
        if not doi:
            return Resolution(key=entry.key, status="unresolved",
                              reason="no doi to look up")

        # Unpaywall refuses every request without an email address (422), and
        # each refusal once read as "not found". None is invented here:
        # OpenAlex carries the same open-access data without one.
        if not self._contact:
            return Resolution(key=entry.key, status="unresolved",
                              reason="skipped: it requires an email address; "
                                     "set SEXTANT_CONTACT to use it")

        payload = fetcher.json(unpaywall_url(doi, self._contact))
        if not payload:
            return Resolution(key=entry.key, status="unresolved",
                              reason="not found in unpaywall")

        if not doi_names_entry(entry, payload.get("title")):
            return different_work(entry, doi, payload.get("title"))

        # Same trap as OpenAlex: is_oa true, url_for_pdf null. And the best
        # location is often the publisher's, which refuses scripts, while a
        # repository's copy sits further down the list.
        locations = payload.get("oa_locations") or [payload.get("best_oa_location") or {}]
        copies = [Copy(loc["url_for_pdf"], version=loc.get("version"),
                       source=loc.get("repository_institution") or "")
                  for loc in locations if loc.get("url_for_pdf")
                  and loc.get("version") != "submittedVersion"]  # the preprint step's
        landing = list(dict.fromkeys(loc["url"] for loc in locations if loc.get("url")))

        got, notes, retry = fetch_first(entry, copies, fetcher, dest_dir, doi=doi)
        if got:
            return Resolution(key=entry.key, status="resolved", doi=doi,
                              pdf_path=str(got.path), version=got.copy.version, resolver=self.name,
                              reason=version_note(got.copy),
                              landing_pages=tuple(landing))

        return Resolution(
            key=entry.key,
            status="no-pdf" if landing else "unresolved",
            reason="; ".join(notes) or ("oa flagged but no url_for_pdf" if payload.get("is_oa")
                                        else "not open access"),
            doi=doi,
            landing_pages=tuple(landing),
            retry=retry,
        )
