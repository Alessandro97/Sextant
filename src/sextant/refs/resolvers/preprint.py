"""A published article's preprint, when no published copy could be had.

Crossref records the link between the two (`has-preprint`), and the record
was already fetched -- and cached -- earlier in the chain, so asking costs
nothing new. The preprint itself is found by DOI: arXiv's own DOIs name the
paper (10.48550/arXiv.<id>), and any other is a free lookup in OpenAlex.

It runs after every source of a published copy, because a preprint can
differ in exactly the figures a citation is checked against. A preprint is
often retitled on publication, and one whose pages do not show the cited
title is not filed.
"""

from pathlib import Path

from sextant.refs.http import Fetcher
from sextant.refs.linkcheck import normalize_doi
from sextant.refs.models import BibEntry, Resolution
from sextant.refs.resolvers import crossref, openalex
from sextant.refs.resolvers.copies import Copy, fetch_first, version_note

_ARXIV_DOI = "10.48550/arxiv."


class PreprintResolver:
    name = "preprint"

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution:
        doi = normalize_doi(entry.doi)
        if not doi:
            return Resolution(key=entry.key, status="unresolved", reason="no doi to look up")

        # The preprints OpenAlex merged into the work, held back until every
        # published copy had been tried. The record is already cached.
        work = fetcher.json(openalex.work_url(doi, openalex.KEY)) or {}
        copies = [c for c in openalex.copies_of(work, keyed_by_doi=False)[0] if c.is_preprint]

        payload = fetcher.json(crossref.crossref_work_url(doi, crossref.CONTACT))
        relations = ((payload or {}).get("message") or {}).get("relation") or {}
        preprints = [normalize_doi(r.get("id")) for r in relations.get("has-preprint") or []
                     if r.get("id-type") == "doi"]
        if not preprints and not copies:
            return Resolution(key=entry.key, status="unresolved",
                              reason="no preprint is recorded")

        for preprint in filter(None, preprints):
            if preprint.lower().startswith(_ARXIV_DOI):
                copies.append(Copy(f"https://arxiv.org/pdf/{preprint[len(_ARXIV_DOI):]}",
                                   version="submittedVersion", source="arXiv",
                                   keyed_by_doi=False))
                continue
            work = fetcher.json(openalex.work_url(preprint, openalex.KEY)) or {}
            for location in work.get("locations") or []:
                if location.get("pdf_url"):
                    # Whatever OpenAlex labels it -- a medRxiv copy came back as
                    # acceptedVersion -- a preprint DOI names a preprint.
                    copies.append(Copy(location["pdf_url"], version="submittedVersion",
                                       source=((location.get("source") or {})
                                               .get("display_name")) or "",
                                       keyed_by_doi=False))

        got, notes, retry = fetch_first(entry, copies, fetcher, dest_dir, doi=doi)
        if got:
            return Resolution(key=entry.key, status="resolved", doi=doi,
                              pdf_path=str(got.path), version=got.copy.version, resolver=self.name,
                              reason=version_note(got.copy))
        return Resolution(key=entry.key, status="unresolved", retry=retry,
                          reason="; ".join(notes) or "its preprint lists no PDF")
