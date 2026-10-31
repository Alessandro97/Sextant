"""PubMed Central, through the routes NCBI allows programs to use.

The OA web service was retired in August 2026, and article PDFs on the PMC
website now answer scripts with a proof-of-work page. "PMC Cloud Service,
PMC OAI-PMH Service, E-Utilities and BioC API are the only services that may
be used" (https://pmc.ncbi.nlm.nih.gov/tools/developers/), and PDFs are in
the Cloud Service only: an anonymous S3 bucket with one folder per article
version (https://pmc-oa-opendata.s3.amazonaws.com/README.txt). The ID
converter finds the article from its DOI
(https://pmc.ncbi.nlm.nih.gov/tools/id-converter-api/).
"""

import re
from pathlib import Path
from urllib.parse import urlencode

from sextant.refs.http import CONTACT, Fetcher
from sextant.refs.linkcheck import normalize_doi
from sextant.refs.models import BibEntry, Resolution
from sextant.refs.resolvers.copies import Copy, fetch_first, version_note
from sextant.refs.resolvers.doi import different_work, doi_names_entry

IDCONV = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com/"


def idconv_url(doi: str, contact: str) -> str:
    query = {"ids": doi, "format": "json", "tool": "sextant"}
    if contact:
        query["email"] = contact
    return f"{IDCONV}?{urlencode(query)}"


def listing_url(pmcid: str) -> str:
    return f"{BUCKET}?{urlencode({'list-type': '2', 'prefix': f'{pmcid}.', 'delimiter': '/'})}"


def metadata_url(pmcid: str, version: int) -> str:
    return f"{BUCKET}metadata/{pmcid}.{version}.json"


def _https(s3_url: str) -> str | None:
    """s3://pmc-oa-opendata/<key>?md5=... as the bucket's HTTPS address."""
    match = re.match(r"s3://pmc-oa-opendata/([^?]+)", s3_url or "")
    return f"{BUCKET}{match.group(1)}" if match else None


class PmcResolver:
    name = "pmc"

    def __init__(self, contact: str | None = None) -> None:
        self._contact = CONTACT if contact is None else contact

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution:
        doi = normalize_doi(entry.doi)
        if not doi:
            return Resolution(key=entry.key, status="unresolved",
                              reason="no doi to look up")

        payload = fetcher.json(idconv_url(doi, self._contact))
        record = ((payload or {}).get("records") or [{}])[0]
        pmcid = record.get("pmcid")
        if not pmcid:
            return Resolution(key=entry.key, status="unresolved", reason="not in PMC")
        if record.get("live") == "false":
            return Resolution(key=entry.key, status="unresolved",
                              reason=f"in PMC, embargoed until {record.get('release-date')}")

        listing = fetcher.text(listing_url(pmcid)) or ""
        versions = sorted({int(v) for v in re.findall(rf"<Prefix>{pmcid}\.(\d+)/</Prefix>",
                                                       listing)}, reverse=True)
        copies = []
        for version in versions:
            meta = fetcher.json(metadata_url(pmcid, version)) or {}
            # The DOI can name another paper, and its PDF shows that DOI.
            if not doi_names_entry(entry, meta.get("title")):
                return different_work(entry, doi, meta.get("title"))
            url = _https(meta.get("pdf_url"))
            if url:
                copies.append(Copy(url, source="PubMed Central",
                                   version="acceptedVersion" if meta.get("is_manuscript")
                                   else "publishedVersion"))

        landing = (f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",)
        got, notes, retry = fetch_first(entry, copies, fetcher, dest_dir, doi=doi)
        if got:
            return Resolution(key=entry.key, status="resolved", doi=doi,
                              pdf_path=str(got.path), version=got.copy.version, resolver=self.name,
                              reason=version_note(got.copy))
        return Resolution(key=entry.key, status="no-pdf", doi=doi, landing_pages=landing,
                          retry=retry,
                          reason="; ".join(notes) or f"{pmcid} has no PDF its licence lets "
                                                     "PMC share")
