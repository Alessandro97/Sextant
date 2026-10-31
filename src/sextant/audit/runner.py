"""Join citation sites to the papers they cite and produce findings.

The verdict for a key with no local PDF is `no-source`, never `not-found`.
Conflating "we could not check" with "the claim is unsupported" would make the
report actively misleading, and on the measured manuscript most references
have no local PDF.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace

from sextant.audit.models import AuditReport, CitationSite, Finding, Quantity
from sextant.audit.quantities import nowhere_note, quantities
from sextant.audit.screen import excerpt_around, screen
from sextant.index.extract import NoTextLayerError, UnreadablePdfError, extract_pages
from sextant.models import Page, Span


class _Sources:
    """Lazy, cached PDF -> Page[] loader. Parses each paper at most once."""

    def __init__(self, paths: Mapping[str, str]) -> None:
        self._paths = paths
        self._cache: dict[str, list[Page] | str] = {}

    def pages(self, key: str) -> list[Page] | str:
        """Pages for `key`, or a string explaining why there are none."""
        if key in self._cache:
            return self._cache[key]

        path = self._paths.get(key)
        if not path:
            result: list[Page] | str = "no local PDF for this reference"
        else:
            try:
                result = extract_pages(path)
            except UnreadablePdfError:
                result = "the local file is unreadable as a PDF"
            except NoTextLayerError:
                result = "the local PDF has no text layer (scanned image?)"

        self._cache[key] = result
        return result


def audit_sites(
    sites: Sequence[CitationSite], pdf_paths: Mapping[str, str]
) -> list[Finding]:
    """One Finding per (site, key) pair."""
    sources = _Sources(pdf_paths)
    findings: list[Finding] = []

    for site in sites:
        claimed = quantities(site.claim)
        joint: list[Finding] = []

        # Every paper of the citation is checked before any finding is written,
        # so a figure one of them gives is not named as missing from another.
        checked = {}
        if claimed:
            for key in site.keys:
                pages = sources.pages(key)
                if not isinstance(pages, str):
                    checked[key] = (pages, [(q, screen(q, pages)) for q in claimed])
        given = {(q.value, q.unit) for _, hits in checked.values()
                 for q, span in hits if span is not None}

        for key in site.keys:
            if not claimed:
                joint.append(
                    Finding(
                        key=key,
                        verdict="no-claim",
                        claim=site.claim,
                        source=site.source,
                        reason="no quantity to check at this citation",
                    )
                )
                continue

            if key not in checked:
                joint.append(
                    Finding(
                        key=key,
                        verdict="no-source",
                        claim=site.claim,
                        quantity=claimed[0],
                        source=site.source,
                        reason=sources.pages(key),
                    )
                )
                continue

            pages, hits = checked[key]
            joint.append(_check(key, site, claimed, pages, hits, given))

        findings += _resolve_joint(joint)

    return findings


def _resolve_joint(joint: Sequence[Finding]) -> list[Finding]:
    """Never fault one paper of \\cite{a,b} for the whole sentence.

    The rule the viewer already follows. A figure found in any of the papers
    answers for all of them, and while any of them cannot be read, none may be
    faulted: the paper holding the figure may be exactly that one.
    """
    located = next((f.key for f in joint if f.verdict == "located"), None)
    unchecked = next((f.key for f in joint if f.verdict == "no-source"), None)

    out: list[Finding] = []
    for finding in joint:
        if finding.verdict == "not-found" and located:
            finding = replace(finding, verdict="no-claim",
                              reason=f"cited jointly; the quantity is in {located}")
        elif finding.verdict == "not-found" and unchecked:
            finding = replace(
                finding, verdict="no-claim",
                reason=(f"cited jointly with {unchecked}, which is not available "
                        "to check, so nothing can be concluded here"))
        out.append(finding)
    return out


def _check(
    key: str,
    site: CitationSite,
    claimed: Sequence[Quantity],
    pages: Sequence[Page],
    hits: Sequence[tuple[Quantity, Span | None]],
    given: Collection[tuple[str, str]],
) -> Finding:
    """`hits` is every figure screened, not just until one is found: the first
    found used to settle the verdict, and a second the paper never gives went
    unmentioned. `given` is what the joint citation's papers located."""
    by_number = {page.number: page for page in pages}
    unfound = [quantity for quantity, span in hits if span is None]

    for quantity, span in hits:
        if span is None:
            continue
        page = by_number[span.page]
        return Finding(
            key=key,
            verdict="located",
            claim=site.claim,
            quantity=quantity,
            span=span,
            source=site.source,
            excerpt=excerpt_around(page.text, span.char_start, span.char_end),
            reason=nowhere_note(unfound, given),
        )

    missing = ", ".join(f"{q.value} {q.unit}" for q in claimed)
    return Finding(
        key=key,
        verdict="not-found",
        claim=site.claim,
        quantity=claimed[0],
        source=site.source,
        reason=f"{missing} appears nowhere in the cited paper",
    )


def audit_manuscript(
    sites: Sequence[CitationSite], pdf_paths: Mapping[str, str]
) -> AuditReport:
    return AuditReport(findings=tuple(audit_sites(sites, pdf_paths)))

