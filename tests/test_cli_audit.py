import json

import pymupdf
from typer.testing import CliRunner

from sextant.cli import app

runner = CliRunner()

TEX = r"""
Field trials report only $3$~Mbit/s per node~\cite{Good}.
Systems reach 99~GHz operation~\cite{Bad}.
Many schemes exist~\cite{Vague}.
"""


def _project(tmp_path):
    (tmp_path / "main.tex").write_text(TEX)
    refs = tmp_path / "refs"
    refs.mkdir()
    for key, body in (
        ("Good", "The measured peak was 3 Mbit/s per node."),
        ("Bad", "This paper is about medieval trade routes."),
        ("Vague", "Assorted schemes."),
    ):
        doc = pymupdf.open()
        doc.new_page().insert_text((72.0, 100.0), body, fontsize=11)
        doc.save(refs / f"{key}.pdf")
        doc.close()
    return tmp_path / "main.tex"


def test_audit_reports_a_verdict_per_citation(tmp_path):
    tex = _project(tmp_path)
    result = runner.invoke(app, ["audit", str(tex), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    verdicts = {f["key"]: f["verdict"] for f in payload["findings"]}
    assert verdicts["Good"] == "located"
    assert verdicts["Bad"] == "not-found"
    assert verdicts["Vague"] == "no-claim"


def test_audit_writes_a_markdown_report(tmp_path):
    tex = _project(tmp_path)
    runner.invoke(app, ["audit", str(tex)])

    report = (tmp_path / "refs" / "AUDIT.md").read_text()
    assert "not-found" in report
    assert "`Bad`" in report


def test_audit_on_a_missing_manuscript_says_so(tmp_path):
    result = runner.invoke(app, ["audit", str(tmp_path / "nope.tex")])
    assert result.exit_code == 1
    assert "cannot read" in result.output


def test_audit_without_a_refs_folder_still_runs_and_says_no_source(tmp_path):
    (tmp_path / "main.tex").write_text(TEX)
    result = runner.invoke(app, ["audit", str(tmp_path / "main.tex"), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["counts"]["no-source"] == 2


def test_a_located_finding_carries_the_page_and_excerpt(tmp_path):
    """The report is only useful if a reader can go straight to the evidence."""
    tex = _project(tmp_path)
    result = runner.invoke(app, ["audit", str(tex), "--json"])

    good = next(f for f in json.loads(result.stdout)["findings"] if f["key"] == "Good")
    assert good["span"]["page"] == 1
    assert "3 Mbit/s" in good["excerpt"]
    assert good["span"]["rects"]


def test_audit_reads_a_paper_filed_under_a_key_with_a_slash(tmp_path):
    from sextant.refs.folder import key_pdf

    key = "DBLP:journals/corr/abs-2005-14165"
    (tmp_path / "main.tex").write_text(
        "Field trials report only $3$~Mbit/s per node~\\cite{" + key + "}.\n")
    refs = tmp_path / "refs"; refs.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), "The peak was 3 Mbit/s per node.",
                               fontsize=11)
    doc.save(key_pdf(refs, key))
    doc.close()

    result = runner.invoke(app, ["audit", str(tmp_path / "main.tex"), "--json"])

    assert result.exit_code == 0, result.output
    verdicts = {f["key"]: f["verdict"] for f in json.loads(result.stdout)["findings"]}
    assert verdicts == {key: "located"}


def test_a_shipped_audit_md_link_does_not_become_the_report(tmp_path):
    tex = _project(tmp_path)
    victim = tmp_path / "bashrc"
    victim.write_text("# the user's own\n")
    (tmp_path / "refs" / "AUDIT.md").symlink_to(victim)

    result = runner.invoke(app, ["audit", str(tex)])

    assert result.exit_code == 0, result.output
    assert victim.read_text() == "# the user's own\n"
    assert "Good" in (tmp_path / "refs" / "AUDIT.md").read_text()
