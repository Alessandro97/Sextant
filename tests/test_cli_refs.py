import json
from pathlib import Path

from typer.testing import CliRunner

from sextant.cli import app

runner = CliRunner()

TEX = r"""
Links below 3 GHz~\cite{Known} and more~\cite{Unknown}.
"""

BIB = """
@article{Known, title={A Known Paper With A Long Title}, doi={10.1/known}, year={2020}}
@article{Unknown, title={An Unfindable Paper With A Long Title}, year={2021}}
"""


def _project(tmp_path):
    (tmp_path / "main.tex").write_text(TEX)
    (tmp_path / "refs.bib").write_text(BIB)
    return tmp_path / "main.tex"


def test_fetch_reports_per_key_outcomes_and_writes_the_folder(tmp_path):
    tex = _project(tmp_path)
    result = runner.invoke(
        app, ["fetch", str(tex), "--db", str(tmp_path / "p.db"), "--offline", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["cited_keys"] == 2
    assert {row["key"] for row in payload["results"]} == {"Known", "Unknown"}
    assert {"resolver", "version", "retry", "reason"} <= set(payload["results"][0])
    assert (tmp_path / "refs" / "MISSING.md").exists()
    assert (tmp_path / "refs" / "inbox").is_dir()


def test_fetch_lists_unresolved_keys_in_missing_md(tmp_path):
    tex = _project(tmp_path)
    runner.invoke(app, ["fetch", str(tex), "--db", str(tmp_path / "p.db"), "--offline"])

    text = (tmp_path / "refs" / "MISSING.md").read_text()
    assert "Known" in text and "Unknown" in text


def test_fetch_on_a_manuscript_with_no_bib_says_so(tmp_path):
    (tmp_path / "main.tex").write_text(TEX)
    result = runner.invoke(
        app, ["fetch", str(tmp_path / "main.tex"), "--db", str(tmp_path / "p.db"), "--offline"]
    )

    assert result.exit_code == 1
    assert "no .bib" in result.output


def test_fetch_on_a_missing_manuscript_says_so(tmp_path):
    result = runner.invoke(
        app, ["fetch", str(tmp_path / "nope.tex"), "--db", str(tmp_path / "p.db")]
    )
    assert result.exit_code == 1
    assert "cannot read" in result.output


def test_linkcheck_reports_a_verdict_per_key(tmp_path):
    tex = _project(tmp_path)
    result = runner.invoke(app, ["linkcheck", str(tex), "--offline", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    verdicts = {row["key"]: row["verdict"] for row in payload["checks"]}
    assert verdicts["Unknown"] == "no-doi"


def test_fetch_adopts_a_pdf_dropped_in_the_inbox(tmp_path, sample_pdf):
    """The manual loop: fetch, drop a file in, re-run, and it is picked up."""
    import shutil

    tex = _project(tmp_path)
    db = tmp_path / "p.db"
    runner.invoke(app, ["fetch", str(tex), "--db", str(db), "--offline"])

    inbox = tmp_path / "refs" / "inbox"
    doc = inbox / "whatever-the-browser-called-it.pdf"
    shutil.copy(sample_pdf, doc)

    # Retitle the copy's first page so it matches the pending entry.
    import pymupdf

    d = pymupdf.open()
    p = d.new_page()
    p.insert_text((72.0, 100.0), "An Unfindable Paper With A Long Title", fontsize=11)
    d.save(doc)
    d.close()

    result = runner.invoke(
        app, ["fetch", str(tex), "--db", str(db), "--offline", "--json"]
    )

    assert json.loads(result.stdout)["resolved"] == 1
    assert (tmp_path / "refs" / "Unknown.pdf").is_symlink()


def test_an_adopted_pdf_enters_the_store_for_next_time(tmp_path, sample_pdf):
    """The point of the store: fetch once, and a later manuscript citing the
    same paper resolves locally instead of going back to the network."""
    import pymupdf
    from sextant.store.db import Store

    tex = _project(tmp_path)
    db = tmp_path / "p.db"
    runner.invoke(app, ["fetch", str(tex), "--db", str(db), "--offline"])

    doc = tmp_path / "refs" / "inbox" / "downloaded.pdf"
    d = pymupdf.open()
    p = d.new_page()
    p.insert_text((72.0, 100.0), "An Unfindable Paper With A Long Title", fontsize=11)
    d.save(doc)
    d.close()

    runner.invoke(app, ["fetch", str(tex), "--db", str(db), "--offline"])

    store = Store.open(db)
    try:
        papers = store.list_papers()
        assert len(papers) == 1, "the adopted PDF never reached the store"
        assert Path(papers[0].path).parent == store.blobs_dir
    finally:
        store.close()
