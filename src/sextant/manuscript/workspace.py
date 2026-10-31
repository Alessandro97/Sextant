"""A manuscript plus everything the reader needs about it.

Status vocabulary matches the audit pipeline, with `located` renamed to
`verified` because that is the word the interface shows. The meaning is
unchanged and just as narrow: the claimed quantity was found in the cited
paper. It is not an assertion that the paper backs the claim.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path

from sextant.audit.models import Quantity
from sextant.audit.quantities import nowhere_note, quantities
from sextant.audit.screen import excerpt_around, screen
from sextant.index.cache import cached_pages
from sextant.index.extract import (
    NoTextLayerError,
    UnreadablePdfError,
)
from sextant.manuscript.bibliography import entries_for, entry_for_citation
from sextant.manuscript.links import CitationMarker, citation_markers
from sextant.models import Page, Paper, Rect, Span
from sextant.refs.folder import key_pdf
from sextant.store.db import Store, content_hash


@dataclass(frozen=True, slots=True)
class MarkerStatus:
    """A citation marker with its verification outcome."""

    key: str
    marker: str
    page: int
    rect: Rect
    claim: str
    context: str
    status: str
    quantity: Quantity | None = None
    span: Span | None = None
    excerpt: str = ""
    reason: str = ""
    #: The figures this paper located, and the sentence's own it did not: what
    #: the group needs to name only a figure none of its papers gives. Not
    #: sent to the browser.
    found: frozenset[tuple[str, str]] = frozenset()
    unfound: tuple[Quantity, ...] = ()


@dataclass(frozen=True, slots=True)
class Reference:
    """One cited work in this manuscript's scoped library."""

    key: str
    marker: str
    cited_count: int
    available: bool
    paper_id: str | None = None
    pages: int = 0
    title: str | None = None
    doi: str | None = None
    #: The bibliography entry exactly as the manuscript prints it. For a
    #: reference no resolver can reach, this is what a human searches with.
    raw: str = ""


@dataclass(frozen=True, slots=True)
class Workspace:
    pdf_path: str
    pages: int
    page_sizes: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    markers: tuple[MarkerStatus, ...] = field(default_factory=tuple)
    references: tuple[Reference, ...] = field(default_factory=tuple)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for marker in self.markers:
            out[marker.status] = out.get(marker.status, 0) + 1
        return out


def build_workspace(pdf_path: Path | str, refs_dir: Path, db_path: Path) -> Workspace:
    """Read the manuscript, verify every marker, and scope the library to it."""
    pdf_path = Path(pdf_path)
    markers = citation_markers(pdf_path)

    sources = _Sources(refs_dir)
    statuses = _resolve_groups(
        [(_verify(marker, sources), marker) for marker in markers]
    )

    import pymupdf

    doc = pymupdf.open(pdf_path)
    try:
        sizes = tuple((page.rect.width, page.rect.height) for page in doc)
    finally:
        doc.close()

    # Titles come from the manuscript's own reference list, so a library
    # built from an uploaded PDF is still readable without a .bib.
    try:
        entries = entries_for(pdf_path)
    except Exception:  # noqa: BLE001 - a title is a nicety, not a blocker
        entries = {}

    store = Store.open(db_path)
    try:
        by_hash = {p.content_hash: p for p in store.list_papers()}

        def stored(path: Path) -> Paper | None:
            """The store's paper with these bytes, adopting a file put in refs/
            by hand -- a reader's own copy, which fetch leaves where it is. With
            no store entry it was checked, but its citations could never be
            opened beside the manuscript or judged. The file is copied, not
            moved, and only once: the copy is found by its hash next time."""
            try:
                digest = content_hash(path)
                if digest not in by_hash:
                    by_hash[digest] = store.adopt_pdf(path)
            except OSError:
                return None
            return by_hash[digest]

        references = _scope_library(markers, sources, stored, entries)
    finally:
        store.close()

    return Workspace(
        pdf_path=str(pdf_path),
        pages=len(sizes),
        page_sizes=sizes,
        markers=statuses,
        references=references,
    )


class _Sources:
    """refs/<key>.pdf, parsed at most once each."""

    def __init__(self, refs_dir: Path) -> None:
        self._dir = Path(refs_dir)
        self._cache: dict[str, list[Page] | str] = {}

    def path(self, key: str) -> Path | None:
        candidate = key_pdf(self._dir, key)
        return candidate if candidate.exists() else None

    def pages(self, key: str) -> list[Page] | str:
        if key in self._cache:
            return self._cache[key]
        path = self.path(key)
        if path is None:
            result: list[Page] | str = "no local PDF for this reference"
        else:
            try:
                result = cached_pages(path)
            except UnreadablePdfError:
                result = "the local file is unreadable as a PDF"
            except NoTextLayerError:
                result = "the local PDF has no text layer (scanned image?)"
        self._cache[key] = result
        return result


def _resolve_groups(pairs) -> tuple[MarkerStatus, ...]:
    """Never fault one member of a joint citation for the whole sentence.

    "Tc = 5 ms ... at the server [24], [25]" cites two papers for one
    statement. Checking each alone reported [25] as not-found for a quantity
    [24] carries, which is an accusation the manuscript does not deserve.

    A quantity found in any member satisfies the group. And if any member
    could not be checked at all, no member may be faulted: the paper holding
    the number may be precisely the one we cannot read. not-found therefore
    survives only when every jointly cited paper was readable and none of them
    contained the quantity.
    """
    verified_in = {m.group for s, m in pairs if s.status == "verified"}
    unchecked_in = {m.group for s, m in pairs if s.status == "no-source"}
    given: dict[int, set] = {}
    for status, marker in pairs:
        given.setdefault(marker.group, set()).update(status.found)

    out: list[MarkerStatus] = []
    for status, marker in pairs:
        if status.status == "verified" and status.unfound:
            # "20 ms and 5 Gbps [1], [2]" is not short of 5 Gbps because [1]
            # lacks it: name only what none of the group's papers gives.
            status = replace(status, reason=nowhere_note(status.unfound,
                                                         given[marker.group]))
        if status.status != "not-found":
            out.append(status)
            continue

        if marker.group in verified_in:
            partner = next(s.key for s, m in pairs
                           if m.group == marker.group and s.status == "verified")
            status = replace(status, status="no-claim",
                             reason=f"cited jointly; the quantity is in {partner}")
        elif marker.group in unchecked_in:
            # The paper carrying the number may be the one we cannot read.
            partner = next(s.key for s, m in pairs
                           if m.group == marker.group and s.status == "no-source")
            status = replace(
                status, status="no-claim",
                reason=(f"cited jointly with {partner}, which is not available "
                        "to check, so nothing can be concluded here"),
            )
        out.append(status)
    return tuple(out)


def _verify(marker: CitationMarker, sources: "_Sources") -> MarkerStatus:
    base = {
        "key": marker.key,
        "marker": marker.marker,
        "page": marker.page,
        "rect": marker.rect,
        "claim": marker.claim,
        "context": marker.context or marker.claim,
    }

    # Credit generously: any quantity in the window is worth looking for.
    claimed = quantities(marker.context or marker.claim)
    # Blame strictly: only the sentence this citation terminates can fault it.
    faultable = {(q.value, q.unit) for q in quantities(marker.claim)}

    if not claimed:
        return MarkerStatus(
            **base, status="no-claim", reason="no quantity to check at this citation"
        )

    pages = sources.pages(marker.key)
    if isinstance(pages, str):
        return MarkerStatus(**base, status="no-source", quantity=claimed[0], reason=pages)

    by_number = {page.number: page for page in pages}
    hits = [(quantity, screen(quantity, pages)) for quantity in claimed]
    unfound = [q for q, span in hits if span is None and (q.value, q.unit) in faultable]

    for quantity, span in hits:
        if span is None:
            continue
        page = by_number[span.page]
        # Found is a place to look, and the sentence's other figures still
        # count: one the paper never gives is named rather than hidden.
        return MarkerStatus(
            **base,
            status="verified",
            quantity=quantity,
            span=span,
            excerpt=excerpt_around(page.text, span.char_start, span.char_end),
            reason=nowhere_note(unfound),
            found=frozenset((q.value, q.unit) for q, s in hits if s is not None),
            unfound=tuple(unfound),
        )

    if not unfound:
        # Everything checkable came from a neighbouring sentence, so this
        # citation is not answerable for it.
        return MarkerStatus(
            **base, status="no-claim",
            reason="the nearby quantities belong to another sentence",
        )

    missing = ", ".join(f"{q.value} {q.unit}" for q in unfound)
    return MarkerStatus(
        **base,
        status="not-found",
        quantity=unfound[0],
        reason=f"{missing} appears nowhere in the cited paper",
    )


def _scope_library(
    markers, sources: "_Sources", stored, entries: dict | None = None
) -> tuple[Reference, ...]:
    entries = entries or {}
    counts: dict[str, int] = {}
    first_marker: dict[str, str] = {}
    for marker in markers:
        counts[marker.key] = counts.get(marker.key, 0) + 1
        first_marker.setdefault(marker.key, marker.marker)

    def order(key: str) -> tuple:
        label = first_marker[key].strip("[]")
        return (0, int(label), key) if label.isdigit() else (1, 0, key)

    references: list[Reference] = []
    for key in sorted(counts, key=order):
        path = sources.path(key)
        # The printed label is the bridge: hyperref hands over "4821377" while
        # the reference list is numbered, and only the marker knows both.
        entry = entry_for_citation(key, first_marker[key], entries)
        paper = stored(path) if path else None
        pages = sources.pages(key)
        references.append(
            Reference(
                key=key,
                marker=first_marker[key],
                cited_count=counts[key],
                available=path is not None,
                paper_id=paper.id if paper else None,
                pages=len(pages) if isinstance(pages, list) else 0,
                title=(entry.title if entry else None)
                or (paper.title if paper else None),
                doi=(entry.doi if entry else None),
                raw=(entry.raw if entry else ""),
            )
        )
    return tuple(references)
