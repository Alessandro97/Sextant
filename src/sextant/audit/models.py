"""Value types for the audit pipeline. Frozen, like everything in models.py.

The verdict vocabulary is deliberately small and deliberately excludes
"supported". A quantity appearing in a paper does not mean the paper supports
the claim -- measured at 2/16 false positives on perturbed values -- so the
pipeline reports where evidence is and lets a reader judge.
"""

from dataclasses import dataclass, field

from sextant.models import Span

#: Every verdict the deterministic pipeline can emit.
VERDICTS = ("located", "not-found", "no-source", "no-claim")


@dataclass(frozen=True, slots=True)
class Quantity:
    """A checkable number-plus-unit lifted out of a claim."""

    value: str
    unit: str
    raw: str


@dataclass(frozen=True, slots=True)
class CitationSite:
    """One \\cite command, with the sentence that leads up to it."""

    keys: tuple[str, ...]
    claim: str
    source: str
    line: int = 0


@dataclass(frozen=True, slots=True)
class Finding:
    """What we can say about one (citation site, cited key) pair."""

    key: str
    verdict: str
    claim: str
    quantity: Quantity | None = None
    span: Span | None = None
    excerpt: str = ""
    reason: str = ""
    source: str = ""


@dataclass(frozen=True, slots=True)
class AuditReport:
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for finding in self.findings:
            out[finding.verdict] = out.get(finding.verdict, 0) + 1
        return out
