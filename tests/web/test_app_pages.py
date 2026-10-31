from starlette.testclient import TestClient

from sextant.store.db import Store
from sextant.web.app import create_app


def _client(tmp_path, sample_pdf):
    db = tmp_path / "papers.db"
    store = Store.open(db)
    store.add_paper(sample_pdf, title="A Paper")
    store.close()
    client = TestClient(create_app(db_path=db), base_url="http://127.0.0.1:8765")
    paper_id = client.get("/api/papers").json()["papers"][0]["id"]
    return client, paper_id


def test_serves_a_page_as_png(tmp_path, sample_pdf):
    client, pid = _client(tmp_path, sample_pdf)

    response = client.get(f"/api/papers/{pid}/page/1.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_page_past_the_end_is_a_404(tmp_path, sample_pdf):
    client, pid = _client(tmp_path, sample_pdf)

    assert client.get(f"/api/papers/{pid}/page/999.png").status_code == 404


def test_locate_returns_overlay_boxes_for_a_quote(tmp_path, sample_pdf):
    """The whole product in one call: a quote in, a page and boxes out."""
    client, pid = _client(tmp_path, sample_pdf)

    body = client.get(
        f"/api/papers/{pid}/locate", params={"q": "aggregate write throughput"}
    ).json()

    assert body["found"] is True
    assert body["page"] == 1
    assert len(body["boxes"]) > 0
    box = body["boxes"][0]
    assert 0.0 <= box["left"] <= 1.0
    assert 0.0 <= box["top"] <= 1.0


def test_locate_finds_a_quote_on_a_later_page(tmp_path, sample_pdf):
    client, pid = _client(tmp_path, sample_pdf)

    body = client.get(f"/api/papers/{pid}/locate", params={"q": "-31 dB/K"}).json()

    assert body["page"] == 2


def test_locate_reports_honestly_when_the_quote_is_not_there(tmp_path, sample_pdf):
    """The grounding invariant, surfaced in the API: no fabricated highlight."""
    client, pid = _client(tmp_path, sample_pdf)

    body = client.get(
        f"/api/papers/{pid}/locate", params={"q": "wholly unrelated sentence about turtles"}
    ).json()

    assert body["found"] is False
    assert body["boxes"] == []


def test_locate_with_an_empty_query_is_rejected(tmp_path, sample_pdf):
    client, pid = _client(tmp_path, sample_pdf)

    assert client.get(f"/api/papers/{pid}/locate", params={"q": "  "}).status_code == 400


def test_the_tour_script_is_served_under_the_asset_version(tmp_path):
    """A cached script is indistinguishable from a broken feature, which is
    why app.js carries the version in its URL. tour.js is no different."""
    client = TestClient(create_app(db_path=tmp_path / "p.db"),
                        base_url="http://127.0.0.1:8765")

    page = client.get("/").text

    assert "/static/tour.js?v=" in page


def test_the_asset_version_changes_when_the_tour_does(tmp_path, monkeypatch):
    import shutil

    from sextant.web import app as web

    copy = tmp_path / "static"
    shutil.copytree(web.STATIC, copy)
    monkeypatch.setattr(web, "STATIC", copy)
    before = web._asset_version()

    (copy / "tour.js").write_text((copy / "tour.js").read_text() + "\n// edited\n")

    assert web._asset_version() != before
