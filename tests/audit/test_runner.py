import pymupdf

from sextant.audit.models import CitationSite
from sextant.audit.runner import audit_sites


def _paper(path, body):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72.0, 100.0), body, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_a_quantity_present_in_the_source_is_located(tmp_path):
    pdf = _paper(tmp_path / "a.pdf", "Peak ingest was 3 Mbit/s in trials.")
    site = CitationSite(keys=("A",), claim="rates reach 3 Mbit/s", source="m.tex")

    (finding,) = audit_sites([site], {"A": str(pdf)})

    assert finding.verdict == "located"
    assert finding.span.page == 1
    assert "3 Mbit/s" in finding.excerpt


def test_a_quantity_absent_from_the_source_is_reported(tmp_path):
    pdf = _paper(tmp_path / "a.pdf", "This paper discusses medieval trade routes only.")
    site = CitationSite(keys=("A",), claim="rates reach 3 Mbit/s", source="m.tex")

    (finding,) = audit_sites([site], {"A": str(pdf)})

    assert finding.verdict == "not-found"
    assert finding.span is None
    assert "3 Mbit/s" in finding.reason


def test_an_unavailable_paper_is_not_confused_with_a_bad_citation():
    """Most references have no local PDF. That is not a citation error."""
    site = CitationSite(keys=("Missing",), claim="rates reach 3 Mbit/s", source="m.tex")

    (finding,) = audit_sites([site], {})

    assert finding.verdict == "no-source"


def test_a_claim_with_no_quantity_is_reported_as_unchecked(tmp_path):
    pdf = _paper(tmp_path / "a.pdf", "Some text.")
    site = CitationSite(keys=("A",), claim="many schemes have been proposed", source="m.tex")

    (finding,) = audit_sites([site], {"A": str(pdf)})

    assert finding.verdict == "no-claim"


def test_a_multi_key_site_produces_one_finding_per_key(tmp_path):
    pdf = _paper(tmp_path / "a.pdf", "Peak was 3 Mbit/s.")
    site = CitationSite(keys=("A", "B"), claim="rates reach 3 Mbit/s", source="m.tex")

    findings = audit_sites([site], {"A": str(pdf)})

    assert {f.key for f in findings} == {"A", "B"}
    assert {f.verdict for f in findings} == {"located", "no-source"}


def test_a_site_with_two_quantities_is_located_if_either_is_found(tmp_path):
    """A citation supporting a compound claim need only anchor one of them for
    the reader to have somewhere to start."""
    pdf = _paper(tmp_path / "a.pdf", "The sampling clock was 5 MHz.")
    site = CitationSite(keys=("A",), claim="3 Mbit/s on a 5 MHz sampling clock", source="m.tex")

    (finding,) = audit_sites([site], {"A": str(pdf)})

    assert finding.verdict == "located"
    assert finding.quantity.unit == "MHz"


def test_an_unreadable_pdf_degrades_to_no_source(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_text("this is not a pdf")
    site = CitationSite(keys=("A",), claim="rates reach 3 Mbit/s", source="m.tex")

    (finding,) = audit_sites([site], {"A": str(bad)})

    assert finding.verdict == "no-source"
    assert "unreadable" in finding.reason.lower()


def test_each_source_pdf_is_parsed_only_once(tmp_path):
    """Two sites citing the same paper must not extract it twice."""
    pdf = _paper(tmp_path / "a.pdf", "Peak was 3 Mbit/s and the clock 5 MHz.")
    sites = [
        CitationSite(keys=("A",), claim="reaches 3 Mbit/s", source="m.tex"),
        CitationSite(keys=("A",), claim="over 5 MHz", source="m.tex"),
    ]

    import sextant.audit.runner as runner_mod

    calls = []
    original = runner_mod.extract_pages

    def counting(path):
        calls.append(path)
        return original(path)

    runner_mod.extract_pages = counting
    try:
        findings = audit_sites(sites, {"A": str(pdf)})
    finally:
        runner_mod.extract_pages = original

    assert len(calls) == 1
    assert all(f.verdict == "located" for f in findings)


def test_a_figure_missing_beside_a_found_one_is_still_reported(tmp_path):
    """The first figure found settled the verdict, and the second, which the
    paper never gives, was not mentioned anywhere."""
    pdf = _paper(tmp_path / "a.pdf", "The measured latency was 20 ms end to end.")
    site = CitationSite(keys=("A",), source="m.tex",
                        claim="latency is 20 ms and throughput is 999 Mbit/s")

    (finding,) = audit_sites([site], {"A": str(pdf)})

    assert finding.verdict == "located"
    assert "999 Mbit/s" in finding.reason


def test_a_jointly_cited_paper_is_not_faulted_for_its_partners_figure(tmp_path):
    """\\cite{A,B} for one figure: the figure in A answers for both."""
    a = _paper(tmp_path / "a.pdf", "Peak ingest was 3 Mbit/s in trials.")
    b = _paper(tmp_path / "b.pdf", "This paper discusses medieval trade routes only.")
    site = CitationSite(keys=("A", "B"), claim="rates reach 3 Mbit/s", source="m.tex")

    found = {f.key: f for f in audit_sites([site], {"A": str(a), "B": str(b)})}

    assert found["A"].verdict == "located"
    assert found["B"].verdict == "no-claim"
    assert "A" in found["B"].reason


def test_no_joint_member_is_faulted_while_a_partner_cannot_be_checked(tmp_path):
    """The paper holding the figure may be exactly the one we cannot read."""
    b = _paper(tmp_path / "b.pdf", "This paper discusses medieval trade routes only.")
    site = CitationSite(keys=("Gone", "B"), claim="rates reach 3 Mbit/s", source="m.tex")

    found = {f.key: f for f in audit_sites([site], {"B": str(b)})}

    assert found["Gone"].verdict == "no-source"
    assert found["B"].verdict == "no-claim"


def test_a_joint_citation_is_faulted_when_every_paper_lacks_the_figure(tmp_path):
    a = _paper(tmp_path / "a.pdf", "Nothing numeric here at all.")
    b = _paper(tmp_path / "b.pdf", "This paper discusses medieval trade routes only.")
    site = CitationSite(keys=("A", "B"), claim="rates reach 3 Mbit/s", source="m.tex")

    found = {f.key: f for f in audit_sites([site], {"A": str(a), "B": str(b)})}

    assert {f.verdict for f in found.values()} == {"not-found"}


def test_a_joint_citation_is_not_told_its_partners_figure_is_missing(tmp_path):
    """\\cite{A,B}: A gives 20 ms, B gives 5 Gbps. Each was told the other's
    figure was nowhere in the cited paper, though the citation holds both."""
    a = _paper(tmp_path / "a.pdf", "Measured latency of 20 ms.")
    b = _paper(tmp_path / "b.pdf", "A capacity of 5 Gbps.")
    site = CitationSite(keys=("A", "B"), source="m.tex",
                        claim="latency is 20 ms and capacity is 5 Gbps")

    found = {f.key: f for f in audit_sites([site], {"A": str(a), "B": str(b)})}

    assert found["A"].verdict == found["B"].verdict == "located"
    assert found["A"].reason == found["B"].reason == ""


def test_a_figure_no_jointly_cited_paper_gives_is_still_named(tmp_path):
    a = _paper(tmp_path / "a.pdf", "Measured latency of 20 ms.")
    b = _paper(tmp_path / "b.pdf", "A capacity of 5 Gbps.")
    site = CitationSite(keys=("A", "B"), source="m.tex",
                        claim="latency is 20 ms, capacity 5 Gbps and range 99 km")

    found = {f.key: f for f in audit_sites([site], {"A": str(a), "B": str(b)})}

    for finding in found.values():
        assert "99 km" in finding.reason
        assert "20 ms" not in finding.reason and "5 Gbps" not in finding.reason


def test_a_figure_found_alone_carries_no_note(tmp_path):
    pdf = _paper(tmp_path / "a.pdf", "Peak ingest was 3 Mbit/s in trials.")
    site = CitationSite(keys=("A",), claim="rates reach 3 Mbit/s", source="m.tex")

    (finding,) = audit_sites([site], {"A": str(pdf)})

    assert finding.verdict == "located"
    assert finding.reason == ""
