import json

from sextant.audit.models import AuditReport, Finding, Quantity
from sextant.audit.report import to_json, to_markdown
from sextant.models import Rect, Span

REPORT = AuditReport(findings=(
    Finding(key="Good", verdict="located", claim="reaches 3 Mbit/s",
            quantity=Quantity("3", "Mbit/s", "3 Mbit/s"),
            span=Span(page=4, char_start=10, char_end=18, rects=(Rect(1.0, 2.0, 3.0, 4.0),)),
            excerpt="peak ingest of 3 Mbit/s observed", source="main.tex"),
    Finding(key="Bad", verdict="not-found", claim="reaches 99 GHz",
            quantity=Quantity("99", "GHz", "99 GHz"),
            reason="99 GHz appears nowhere in the cited paper", source="main.tex"),
    Finding(key="Gone", verdict="no-source", claim="reaches 5 MHz",
            reason="no local PDF for this reference", source="main.tex"),
    Finding(key="Vague", verdict="no-claim", claim="has been studied", source="main.tex"),
))


def test_markdown_puts_actionable_findings_first():
    md = to_markdown(REPORT)
    assert md.index("not-found") < md.index("no-source")


def test_markdown_shows_the_page_for_a_located_finding():
    assert "p. 4" in to_markdown(REPORT)


def test_markdown_shows_the_excerpt_so_a_reader_can_judge():
    assert "peak ingest of 3 Mbit/s observed" in to_markdown(REPORT)


def test_markdown_never_claims_a_citation_is_supported():
    """The measurement forbids it. Guard against a future well-meaning edit."""
    assert "supported" not in to_markdown(REPORT).lower()


def test_markdown_states_the_counts():
    md = to_markdown(REPORT)
    assert "1 located" in md and "1 not-found" in md


def test_json_round_trips_every_finding():
    payload = json.loads(to_json(REPORT))
    assert len(payload["findings"]) == 4
    assert payload["counts"]["located"] == 1


def test_json_carries_the_span_for_a_viewer_to_highlight():
    payload = json.loads(to_json(REPORT))
    located = next(f for f in payload["findings"] if f["verdict"] == "located")
    assert located["span"]["page"] == 4
    assert located["span"]["rects"][0] == [1.0, 2.0, 3.0, 4.0]


def test_json_span_is_null_when_nothing_was_located():
    payload = json.loads(to_json(REPORT))
    bad = next(f for f in payload["findings"] if f["key"] == "Bad")
    assert bad["span"] is None
