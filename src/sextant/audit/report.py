"""Render an AuditReport for a human and for a machine.

Ordering is by actionability, not alphabetically: `not-found` is the only
verdict that points at a possible citation error, so it leads.
"""

import json

from sextant.audit.models import AuditReport, Finding

#: Most actionable first.
_ORDER = ("not-found", "located", "no-source", "no-claim")

_HEADINGS = {
    "not-found": "not-found — the claimed quantity is absent from the cited paper",
    "located": "located — the quantity is in the cited paper; check the context",
    "no-source": "no-source — no local PDF, so nothing could be checked",
    "no-claim": "no-claim — no checkable quantity at this citation",
}


def to_markdown(report: AuditReport) -> str:
    counts = report.counts()
    summary = ", ".join(f"{counts[v]} {v}" for v in _ORDER if v in counts)

    lines = [
        "# Citation audit",
        "",
        f"{len(report.findings)} citation-key pairs: {summary}.",
        "",
        "A `located` result means the quantity appears in the cited paper. It is "
        "not a judgement that the paper backs the claim — read the excerpt.",
        "",
    ]

    for verdict in _ORDER:
        group = [f for f in report.findings if f.verdict == verdict]
        if not group:
            continue
        lines += [f"## {_HEADINGS[verdict]}", ""]
        for finding in group:
            lines += _entry(finding)
        lines.append("")

    return "\n".join(lines)


def _entry(finding: Finding) -> list[str]:
    out = [f"### `{finding.key}`", "", f"- **Claim:** {finding.claim}"]
    if finding.quantity:
        out.append(f"- **Checked:** {finding.quantity.value} {finding.quantity.unit}")
    if finding.span:
        out.append(
            f"- **Found:** p. {finding.span.page}, chars "
            f"{finding.span.char_start}–{finding.span.char_end}"
        )
        out.append(f"- **Context:** …{finding.excerpt}…")
    if finding.reason:
        out.append(f"- **Note:** {finding.reason}")
    out.append("")
    return out


def to_json(report: AuditReport) -> str:
    return json.dumps(
        {
            "counts": report.counts(),
            "findings": [_as_dict(f) for f in report.findings],
        },
        indent=2,
    )


def _as_dict(finding: Finding) -> dict:
    return {
        "key": finding.key,
        "verdict": finding.verdict,
        "claim": finding.claim,
        "source": finding.source,
        "quantity": (
            {"value": finding.quantity.value, "unit": finding.quantity.unit}
            if finding.quantity
            else None
        ),
        "span": (
            {
                "page": finding.span.page,
                "char_start": finding.span.char_start,
                "char_end": finding.span.char_end,
                "rects": [[r.x0, r.y0, r.x1, r.y1] for r in finding.span.rects],
            }
            if finding.span
            else None
        ),
        "excerpt": finding.excerpt,
        "reason": finding.reason,
    }
