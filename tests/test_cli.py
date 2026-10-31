import json

import pytest
from typer.testing import CliRunner

from sextant.ground.ground import GroundingError
from sextant.cli import app
from sextant.store.db import Store

runner = CliRunner()


def test_index_reports_pages_and_persists(tmp_path, sample_pdf):
    db = tmp_path / "papers.db"
    result = runner.invoke(app, ["index", str(sample_pdf), "--db", str(db), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["pages"] == 2
    assert payload["index_status"] == "ok"
    assert db.exists()


def test_index_is_idempotent(tmp_path, sample_pdf):
    db = tmp_path / "papers.db"
    first = runner.invoke(app, ["index", str(sample_pdf), "--db", str(db), "--json"])
    second = runner.invoke(app, ["index", str(sample_pdf), "--db", str(db), "--json"])

    assert json.loads(first.stdout)["paper_id"] == json.loads(second.stdout)["paper_id"]


def test_index_reports_no_text_layer_without_crashing(tmp_path, blank_pdf):
    db = tmp_path / "papers.db"
    result = runner.invoke(app, ["index", str(blank_pdf), "--db", str(db), "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["index_status"] == "no-text-layer"


def test_locate_prints_page_and_rects(tmp_path, sample_pdf):
    db = tmp_path / "papers.db"
    indexed = runner.invoke(app, ["index", str(sample_pdf), "--db", str(db), "--json"])
    paper_id = json.loads(indexed.stdout)["paper_id"]

    result = runner.invoke(
        app,
        ["locate", paper_id, "aggregate write throughput", "--db", str(db), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["page"] == 1
    assert len(payload["rects"]) == 3


def test_locate_exits_nonzero_when_text_is_absent(tmp_path, sample_pdf):
    db = tmp_path / "papers.db"
    indexed = runner.invoke(app, ["index", str(sample_pdf), "--db", str(db), "--json"])
    paper_id = json.loads(indexed.stdout)["paper_id"]

    result = runner.invoke(
        app, ["locate", paper_id, "not present anywhere", "--db", str(db), "--json"]
    )
    assert result.exit_code == 1


def test_ask_without_api_key_fails_fast_with_guidance(tmp_path, sample_pdf, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db = tmp_path / "papers.db"
    indexed = runner.invoke(app, ["index", str(sample_pdf), "--db", str(db), "--json"])
    paper_id = json.loads(indexed.stdout)["paper_id"]

    result = runner.invoke(app, ["ask", "anything?", "--paper", paper_id, "--db", str(db)])

    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_ask_reports_a_grounding_failure_cleanly(tmp_path, sample_pdf, monkeypatch):
    """An API failure must reach the user as a message, not a traceback."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    db = tmp_path / "papers.db"
    indexed = runner.invoke(app, ["index", str(sample_pdf), "--db", str(db), "--json"])
    paper_id = json.loads(indexed.stdout)["paper_id"]

    def boom(*args, **kwargs):
        raise GroundingError("request to Claude failed: connection error")

    monkeypatch.setattr("sextant.cli.ground", boom)

    result = runner.invoke(app, ["ask", "anything?", "--paper", paper_id, "--db", str(db)])

    assert result.exit_code == 1
    assert "request to Claude failed" in result.output


def test_ask_on_an_unknown_paper_says_so(tmp_path, sample_pdf, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    db = tmp_path / "papers.db"

    result = runner.invoke(app, ["ask", "q?", "--paper", "nosuchid", "--db", str(db)])

    assert result.exit_code == 1
    assert "nosuchid" in result.output


def test_ask_on_a_registered_but_unindexed_paper_says_so(
    tmp_path, sample_pdf, monkeypatch
):
    """The branch the previous test's name claimed but never reached.

    A paper can be registered in the store yet have no pages — that is a
    different failure from an unknown id, and it tells the user to run
    `index` rather than that the paper does not exist.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    db = tmp_path / "papers.db"
    store = Store.open(db)
    paper = store.add_paper(sample_pdf)  # registered, never indexed
    store.close()

    result = runner.invoke(app, ["ask", "q?", "--paper", paper.id, "--db", str(db)])

    assert result.exit_code == 1
    assert "not indexed" in result.output


def test_index_reports_a_missing_file_cleanly(tmp_path):
    """A typo'd path must not produce a traceback."""
    db = tmp_path / "papers.db"
    result = runner.invoke(
        app, ["index", str(tmp_path / "nope.pdf"), "--db", str(db)]
    )

    assert result.exit_code == 1
    assert "cannot read" in result.output
    assert "Traceback" not in result.output


def test_index_reports_a_corrupt_pdf_cleanly(tmp_path):
    """Some of a 251-file corpus will not be valid PDFs."""
    db = tmp_path / "papers.db"
    bad = tmp_path / "corrupt.pdf"
    bad.write_text("this is plainly not a PDF")

    result = runner.invoke(app, ["index", str(bad), "--db", str(db), "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["index_status"] == "unreadable"


def test_a_key_in_dotenv_is_found_before_a_command_runs(tmp_path, monkeypatch):
    """The wiring, not the parser: a reader who put a key in .env as every
    version of the docs told them to must have it found."""
    import os

    from typer.testing import CliRunner

    from sextant.cli import app as cli_app

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-from-dotenv\n")
    monkeypatch.chdir(tmp_path)

    CliRunner().invoke(cli_app, ["locate", "nope", "text"])

    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-from-dotenv"
