"""Resolver protocol and the chain that runs them.

Each resolver is small, independent, and behind one interface, so the chain is
just a list and adding a source is additive.
"""

from dataclasses import replace
from pathlib import Path
from typing import Protocol, Sequence

from sextant.refs.http import Fetcher, Unavailable
from sextant.refs.linkcheck import normalize_doi
from sextant.refs.models import BibEntry, Resolution


class Resolver(Protocol):
    name: str

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution: ...


def resolve_chain(
    entry: BibEntry,
    resolvers: Sequence[Resolver],
    fetcher: Fetcher,
    dest_dir: Path,
) -> Resolution:
    """Run resolvers in order. First PDF wins; everything else accumulates.

    Even when no PDF is found, the chain is worth running to the end: a
    resolver that cannot download can still contribute a DOI or a landing page
    that makes manual retrieval a single click.
    """
    landing: list[str] = []
    similar: list[str] = []
    reasons: list[str] = []
    doi = normalize_doi(entry.doi)
    title = entry.title
    retry = False
    wrong_doi = False
    doi_is_preprint = False

    for resolver in resolvers:
        # A DOI one source found by title is the key every later source needs.
        # The bibliography's own is never replaced -- and one shown to name
        # another work is handed to no one.
        if wrong_doi:
            asked = replace(entry, doi=None)
        elif normalize_doi(entry.doi) or not doi:
            asked = entry
        else:
            asked = replace(entry, doi=doi, doi_found=True, doi_is_preprint=doi_is_preprint)
        try:
            result = resolver.resolve(asked, fetcher, dest_dir)
        except Unavailable as exc:
            reasons.append(f"{resolver.name}: no answer ({exc}), try again later")
            retry = True
            continue
        except Exception as exc:
            # One flaky upstream must not abort an acquisition run.
            reasons.append(f"{resolver.name}: {type(exc).__name__}")
            continue

        if not doi and result.doi:
            doi_is_preprint = result.doi_is_preprint
        doi = doi or result.doi
        title = result.title or title
        retry = retry or result.retry
        wrong_doi = wrong_doi or result.wrong_doi
        for page in result.landing_pages:
            if page not in landing:
                landing.append(page)
        similar += [copy for copy in result.similar if copy not in similar]

        if result.pdf_path:
            return Resolution(
                key=entry.key,
                status="resolved",
                reason=result.reason,
                doi=doi,
                title=title,
                pdf_path=result.pdf_path,
                resolver=resolver.name,
                landing_pages=tuple(landing),
                version=result.version,
            )

        if result.reason:
            reasons.append(f"{resolver.name}: {result.reason}")
        if result.final:
            break

    return Resolution(
        key=entry.key,
        status="no-pdf" if landing else "unresolved",
        reason="; ".join(reasons),
        doi=doi,
        title=title,
        landing_pages=tuple(landing),
        retry=retry,
        similar=tuple(similar),
    )
