"""What the fetch route records as having been attempted.

The automatic fetch on open asks only for keys never attempted, so anything
wrongly written into that record suppresses fetching permanently -- silently,
and only on the reader's own machine.
"""

import pytest
from starlette.testclient import TestClient

from sextant.chat import compose
from sextant.refs.pipeline import attempted_keys
from sextant.web.app import create_app


@pytest.fixture(autouse=True)
def never_shell_out(monkeypatch):
    monkeypatch.setattr(compose, "cli_available", lambda: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def never_hit_the_network(monkeypatch):
    """Offline: what is under test is the bookkeeping, not the resolvers."""
    from sextant.refs import pipeline

    monkeypatch.setattr(pipeline, "build_resolvers", lambda store, offline: [])


def test_a_key_no_resolver_ever_saw_is_not_recorded_as_attempted(
        tmp_path, latex_like_manuscript):
    """A key absent from the bibliography reaches no resolver, so recording it
    marks a fetch that never happened as tried. That is how a real refs/ folder
    came to hold 32 attempted keys after 32 fetches that never left the
    machine: once the bibliography parsed and the keys became resolvable, the
    reader still had to fetch by hand on every open."""
    pdf = latex_like_manuscript(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    client.post("/api/workspace/fetch",
                json={"path": str(pdf), "keys": ["4821377", "not-a-reference"],
                      "offline": True})

    recorded = attempted_keys(tmp_path / "refs")

    assert "not-a-reference" not in recorded, (
        "a key no resolver saw was recorded as attempted")
    assert "4821377" in recorded, "a key that did reach the chain is remembered"


def test_a_fetch_that_could_look_nothing_up_leaves_the_work_outstanding(
        tmp_path, latex_like_manuscript, monkeypatch):
    """The exact shape of the reported failure. While the bibliography was
    keyed differently from the citations, every fetch resolved nothing -- and
    wrote all 32 keys down as attempted. `unattempted` then came back empty on
    every open, so auto-build did nothing and the reader concluded, correctly,
    that they had to connect each paper by hand."""
    from sextant.web import app as web_app

    monkeypatch.setattr(web_app, "load_entries", lambda pdf: {})
    pdf = latex_like_manuscript(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    client.post("/api/workspace/fetch", json={"path": str(pdf), "offline": True})
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert ws["unattempted"], (
        "every reference was written off by a fetch that tried none of them")


def test_a_key_whose_source_did_not_answer_is_tried_again_on_the_next_open(
        tmp_path, latex_like_manuscript, monkeypatch):
    """arXiv throttled a run, and the keys it never answered for were written
    off as attempted: the viewer would not have tried them again."""
    from sextant.refs import pipeline
    from sextant.refs.http import Unavailable

    class Busy:
        name = "arxiv"

        def resolve(self, entry, fetcher, dest_dir):
            raise Unavailable("HTTP 429")

    monkeypatch.setattr(pipeline, "build_resolvers", lambda store, offline: [Busy()])
    pdf = latex_like_manuscript(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.post("/api/workspace/fetch",
                           json={"path": str(pdf), "keys": ["4821377"], "offline": True})

    assert "4821377" not in attempted_keys(tmp_path / "refs")
    (row,) = response.json()["results"]
    assert "try again later" in row["reason"]
