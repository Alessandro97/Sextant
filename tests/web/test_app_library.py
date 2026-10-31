from starlette.testclient import TestClient

from sextant.store.db import Store
from sextant.web.app import create_app


def _client(tmp_path, sample_pdf):
    db = tmp_path / "papers.db"
    store = Store.open(db)
    store.add_paper(sample_pdf, title="Seasonal Grazing Patterns")
    store.close()
    return TestClient(create_app(db_path=db), base_url="http://127.0.0.1:8765")


def test_health_reports_ok(tmp_path, sample_pdf):
    assert _client(tmp_path, sample_pdf).get("/api/health").json()["status"] == "ok"


def test_library_lists_papers_in_the_store(tmp_path, sample_pdf):
    papers = _client(tmp_path, sample_pdf).get("/api/papers").json()["papers"]

    assert len(papers) == 1
    assert papers[0]["title"] == "Seasonal Grazing Patterns"
    assert papers[0]["id"]


def test_library_does_not_leak_absolute_paths(tmp_path, sample_pdf):
    """The browser has no use for a filesystem path and it should not sit in
    a payload that might be pasted into a bug report."""
    papers = _client(tmp_path, sample_pdf).get("/api/papers").json()["papers"]

    assert "path" not in papers[0]


def test_paper_detail_reports_the_page_count(tmp_path, sample_pdf):
    client = _client(tmp_path, sample_pdf)
    paper_id = client.get("/api/papers").json()["papers"][0]["id"]

    detail = client.get(f"/api/papers/{paper_id}").json()

    assert detail["pages"] == 2
    assert detail["width"] > 0 and detail["height"] > 0


def test_an_unknown_paper_is_a_404(tmp_path, sample_pdf):
    assert _client(tmp_path, sample_pdf).get("/api/papers/nope").status_code == 404


def test_the_index_page_is_served(tmp_path, sample_pdf):
    response = _client(tmp_path, sample_pdf).get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
