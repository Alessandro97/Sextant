"""Searching the open documents."""

import pymupdf
from starlette.testclient import TestClient

from sextant.store.db import Store
from sextant.web.app import create_app


def _manuscript(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72.0, 100.0), "The ingest budget assumes a 5 MHz clock rate [1].",
                     fontsize=11)
    page.insert_link({"kind": pymupdf.LINK_NAMED,
                      "from": pymupdf.Rect(300, 91, 316, 102), "name": "cite.K"})
    doc.save(path)
    doc.close()
    return path


def test_a_word_is_found_in_the_manuscript(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.get("/api/workspace/find",
                      params={"path": str(pdf), "q": "ingest"}).json()

    assert body["total"] == 1
    assert body["hits"][0]["page"] == 1
    assert body["hits"][0]["boxes"], "a hit must be paintable"


def test_a_hit_carries_its_surroundings(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.get("/api/workspace/find",
                      params={"path": str(pdf), "q": "5 MHz"}).json()

    assert "clock" in body["hits"][0]["text"]


def test_a_word_that_is_absent_finds_nothing(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.get("/api/workspace/find",
                      params={"path": str(pdf), "q": "zebra"}).json()

    assert body == {"hits": [], "total": 0, "shown": 0}


def test_the_cited_paper_can_be_searched_too(tmp_path, sample_pdf):
    db = tmp_path / "p.db"
    store = Store.open(db)
    store.add_paper(sample_pdf, title="A Paper")
    store.close()
    client = TestClient(create_app(db_path=db), base_url="http://127.0.0.1:8765")
    paper_id = client.get("/api/papers").json()["papers"][0]["id"]

    body = client.get(f"/api/papers/{paper_id}/find",
                      params={"q": "aggregate write throughput"}).json()

    assert body["total"] == 1
    assert body["hits"][0]["boxes"]


def test_searching_an_unknown_paper_is_a_404(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    assert client.get("/api/papers/nope/find", params={"q": "x"}).status_code == 404
