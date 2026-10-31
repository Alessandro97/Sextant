"""The reference-acquisition pipeline, shared by the CLI and the web app.

Extracted so `sextant fetch` and the viewer's Fetch button cannot drift apart.
Both need the same resolver order, the same staging directory, the same
adoption-into-the-store rule, and the same symlink farm.
"""

import json
import subprocess
import tempfile
from collections.abc import Collection, Iterable, Sequence
from dataclasses import replace
from pathlib import Path

from sextant.refs.bibtex import parse_bib
from sextant.refs.cache import CachingFetcher
from sextant.refs.convert import (
    CONVERTIBLE,
    ConversionUnavailableError,
    to_pdf,
)
from sextant.refs.folder import downloads_dir, materialize
from sextant.refs.http import FakeFetcher, HttpFetcher
from sextant.refs.inbox import adopt
from sextant.refs.models import BibEntry, Resolution
from sextant.refs.resolvers import resolve_chain
from sextant.refs.resolvers.arxiv import ArxivResolver
from sextant.refs.resolvers.crossref import CrossrefResolver
from sextant.refs.resolvers.itu import ItuResolver
from sextant.refs.resolvers.local import LocalResolver
from sextant.refs.resolvers.openalex import OpenAlexResolver
from sextant.refs.resolvers.pmc import PmcResolver
from sextant.refs.resolvers.preprint import PreprintResolver
from sextant.refs.resolvers.threegpp import ThreeGppResolver
from sextant.refs.resolvers.unpaywall import UnpaywallResolver
from sextant.safefs import real_dir, write_file
from sextant.store.db import Store


def load_entries(near: Path) -> dict[str, BibEntry]:
    """Every bib entry at or below `near`'s directory.

    A manuscript directory routinely holds several .bib files (a submission
    copy, a revision). Merging them all and selecting by key is more forgiving
    than making the user name the right one.

    Falls back to the PDF's own reference list when no .bib is present, which
    is the normal case for a PDF uploaded on its own.
    """
    root = Path(near).resolve()
    pdf = root if root.suffix.lower() == ".pdf" else None
    root = root if root.is_dir() else root.parent

    entries: dict[str, BibEntry] = {}
    for bib in sorted(root.rglob("*.bib")):
        entries.update(parse_bib(bib.read_text(errors="ignore")))

    if not entries and pdf is not None:
        try:
            entries = _entries_from_pdf(pdf)
        except Exception:  # noqa: BLE001 - a malformed PDF must not break fetch
            entries = {}
    return entries


def _entries_from_pdf(pdf: Path) -> dict[str, BibEntry]:
    """The PDF's own reference list, keyed by the citation keys the rest of
    Sextant uses.

    The reference list is keyed by its printed labels -- "1", "2", ... --
    while hyperref hands the reader keys like "4821377". Returning the list's
    own keys meant every lookup missed: the fetch route selected no entries at
    all and reported every reference as "not in any .bib file", so arXiv was
    never even contacted for papers that are sitting on arXiv.
    """
    from sextant.manuscript.bibliography import (as_bib_entries, entries_for,
                                                 entry_for_citation)
    from sextant.manuscript.links import citation_markers

    by_label = as_bib_entries(pdf)
    printed = entries_for(pdf)

    markers = citation_markers(pdf)
    if not markers:
        return by_label

    first: dict[str, str] = {}
    for marker in markers:
        first.setdefault(marker.key, marker.marker)

    keyed: dict[str, BibEntry] = {}
    for key, label in first.items():
        found = entry_for_citation(key, label, printed)
        entry = by_label.get(found.key) if found else None
        if entry:
            keyed[key] = replace(entry, key=key)
    return keyed or by_label


def build_resolvers(store: Store, offline: bool) -> list:
    """Resolver chain, cheapest and most certain first."""
    # Standards come first: recognised by number, never searched for by title.
    resolvers = [LocalResolver(store), ThreeGppResolver(), ItuResolver()]
    if not offline:
        # Crossref first: free, and it finds the DOI every later source is
        # keyed by. arXiv last: its search is by title, and its terms allow
        # one query every three seconds. Most preprints it holds, OpenAlex
        # lists first.
        # The preprint step comes after every published copy: a preprint can
        # differ in exactly the figures a citation is checked against.
        resolvers += [CrossrefResolver(), OpenAlexResolver(), PmcResolver(),
                      UnpaywallResolver(), PreprintResolver(), ArxivResolver()]
    return resolvers


def fetch_references(
    entries: Iterable[BibEntry],
    store: Store,
    out: Path,
    offline: bool = False,
) -> list[Resolution]:
    """Resolve `entries` into `out`, adopting anything obtained into the store."""
    real_dir(out)
    real_dir(out / "inbox")
    # Resolvers download here, not into out itself: a download named
    # "{key}.pdf" beside the symlink farm would be its own link target.
    staging = real_dir(downloads_dir(out))

    fetcher = FakeFetcher() if offline else CachingFetcher(HttpFetcher(), store)
    resolvers = build_resolvers(store, offline)

    results = [resolve_chain(entry, resolvers, fetcher, staging) for entry in entries]

    adopted = adopt(out / "inbox", [r for r in results if not r.pdf_path])
    by_key = {r.key: r for r in results}
    for r in adopted:
        by_key[r.key] = r
    results = list(by_key.values())

    # Anything Sextant fetched or a human dropped belongs to the store, so the
    # next manuscript citing it resolves locally instead of going back to the
    # network. Papers the local resolver found are already registered —
    # re-adopting would copy an external file the store does not own.
    for i, r in enumerate(results):
        if r.pdf_path and r.resolver != "local":
            paper = store.adopt_pdf(r.pdf_path, title=r.title)
            results[i] = replace(r, pdf_path=paper.path)

    materialize(results, out)
    return results


def resolution_rows(results: Sequence[Resolution]) -> list[dict]:
    """Resolutions as plain dicts, for JSON responses."""
    return [
        {
            "key": r.key,
            "status": r.status,
            "reason": r.reason,
            "title": r.title,
            "doi": r.doi,
            "resolver": r.resolver,
            "version": r.version,
            "retry": r.retry,
            "landing_pages": list(r.landing_pages),
            "similar": list(r.similar),
            "available": bool(r.pdf_path),
        }
        for r in results
    ]


#: Where we remember which keys have already been tried for this manuscript.
ATTEMPTS_FILE = ".sextant-attempts.json"


def attempted_keys(out: Path) -> set[str]:
    """Keys this refs/ folder has already had a fetch attempted for.

    Without this the viewer re-fetches on every open. A reference behind a
    paywall will never resolve, and retrying it each time the manuscript is
    opened is pure noise on the network and in the interface.
    """
    path = Path(out) / ATTEMPTS_FILE
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()).get("keys", []))
    except (json.JSONDecodeError, OSError):
        return set()


def record_attempts(out: Path, keys: Iterable[str]) -> None:
    """Add `keys` to the attempted set. Never removes: a key that failed once
    is still worth a manual retry, but not an automatic one."""
    path = Path(out) / ATTEMPTS_FILE
    merged = sorted(attempted_keys(out) | set(keys))
    write_file(path, json.dumps({"keys": merged}, indent=2))


def convertible_files(out: Path) -> list[Path]:
    """Office documents sitting in the refs folder or its inbox."""
    out = Path(out)
    found: list[Path] = []
    for directory in (out, out / "inbox"):
        if not directory.is_dir():
            continue
        found += [p for p in sorted(directory.glob("*"))
                  if p.is_file() and p.suffix.lower() in CONVERTIBLE]
    return found


def pending_conversions(out: Path) -> list[Path]:
    """Office documents that still need converting.

    A document whose PDF already exists and is newer is done, and listing it
    as outstanding tells the reader their conversion did nothing.
    """
    inbox = Path(out) / "inbox"
    waiting = []
    for document in convertible_files(out):
        made = inbox / f"{document.stem}.pdf"
        if made.exists() and made.stat().st_mtime >= document.stat().st_mtime:
            continue
        waiting.append(document)
    return waiting


def convert_dropped_documents(
    out: Path, only: Collection[str] | None = None
) -> list[dict]:
    """Turn any .doc/.docx the user added into PDFs the rest of Sextant reads.

    3GPP publishes specifications as .doc, and those are precisely the
    references no resolver can fetch -- so this is the format most likely to be
    added by hand. Silently skipping them, as the plain *.pdf glob did, wastes
    the user's time with no explanation.

    `only` names the files to convert, by filename. A 27 MB specification takes
    tens of seconds, so converting four of them to get at one is a poor trade
    the reader should not be forced into. None means all of them.
    """
    results: list[dict] = []
    wanted = None if only is None else set(only)
    for document in convertible_files(out):
        if wanted is not None and document.name not in wanted:
            continue
        try:
            pdf = to_pdf(document, Path(out) / "inbox")
            results.append({"source": document.name, "pdf": pdf.name, "error": ""})
        except (ConversionUnavailableError, RuntimeError, OSError,
                subprocess.TimeoutExpired) as exc:
            results.append({"source": document.name, "pdf": None, "error": str(exc)})
    return results


def rescan_folder(out: Path, pending: Sequence[Resolution],
                  convert_only: Collection[str] | None = None) -> list[Resolution]:
    """Look for manually-added PDFs anywhere in the refs folder.

    Covers both `refs/inbox/` and loose files dropped straight into `refs/`,
    because telling someone "put it in inbox/" and then ignoring the file they
    put next to it is a bad trade for one glob.

    Symlinks are skipped: those are the farm this function's own output
    creates, and re-adopting them would match a reference against a paper
    already filed under a different key.
    """
    out = Path(out)
    if not out.is_dir():
        return []

    # Self-contained on purpose: any caller can hand us a folder and get the
    # office documents in it considered. Repeating a conversion the route
    # already did is free -- to_pdf reuses an output newer than its source.
    #
    # `convert_only` has to be honoured here too. Converting everything at this
    # point silently undid the reader's selection: they picked one 27 MB
    # specification and got all four.
    convert_dropped_documents(out, only=convert_only)

    adopted = list(adopt(out / "inbox", pending))
    claimed = {r.key for r in adopted}
    remaining = [r for r in pending if r.key not in claimed]
    if not remaining:
        return adopted

    # adopt() scans a directory, so loose files in refs/ are presented to it
    # through a throwaway directory of symlinks rather than by moving anything.
    # Nothing the user put there is touched.
    #
    # A fresh directory of Sextant's own, and only the links it made are
    # removed. A fixed name let a folder someone sent ship refs/.loose as a
    # link to ~/Documents, and clearing it deleted everything in there.
    staging = Path(tempfile.mkdtemp(dir=real_dir(out), prefix=".loose-"))
    links: list[Path] = []
    try:
        for candidate in sorted(out.glob("*.pdf")):
            if candidate.is_symlink():
                continue
            link = staging / candidate.name
            link.symlink_to(candidate.resolve())
            links.append(link)

        adopted += adopt(staging, remaining)
    finally:
        for link in links:
            link.unlink()
        staging.rmdir()

    # Point adopted resolutions at the real file, not the vanished link.
    fixed: list[Resolution] = []
    for resolution in adopted:
        path = Path(resolution.pdf_path) if resolution.pdf_path else None
        if path and path.parent == staging:
            resolution = replace(resolution, pdf_path=str(out / path.name))
        fixed.append(resolution)
    return fixed
