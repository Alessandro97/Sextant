from sextant.audit.models import AuditReport, CitationSite, Finding, Quantity
from sextant.models import Rect, Span


def test_quantity_keeps_the_raw_text_it_came_from():
    q = Quantity(value="3", unit="Mbit/s", raw="3~Mbit/s")
    assert q.value == "3"
    assert q.raw == "3~Mbit/s"


def test_citation_site_can_carry_several_keys():
    site = CitationSite(keys=("a", "b"), claim="Rates reach 3 Mbit/s.", source="main.tex")
    assert len(site.keys) == 2


def test_a_located_finding_carries_the_span_that_proves_it():
    span = Span(page=4, char_start=10, char_end=20, rects=(Rect(0.0, 0.0, 1.0, 1.0),))
    f = Finding(key="k", verdict="located", claim="c", span=span, excerpt="3 Mbit/s peak")
    assert f.span.page == 4
    assert "3 Mbit/s" in f.excerpt


def test_a_not_found_finding_has_no_span():
    f = Finding(key="k", verdict="not-found", claim="c", reason="21 GHz absent")
    assert f.span is None


def test_report_counts_by_verdict():
    report = AuditReport(findings=(
        Finding(key="a", verdict="located", claim="c"),
        Finding(key="b", verdict="not-found", claim="c"),
        Finding(key="c", verdict="not-found", claim="c"),
    ))
    assert report.counts() == {"located": 1, "not-found": 2}
