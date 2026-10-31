import pymupdf
from starlette.testclient import TestClient

from sextant.web.app import create_app


def _pdf_bytes(with_links=True):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72.0, 100.0), "Rates reach 3 Mbit/s [1]", fontsize=11)
    if with_links:
        page.insert_link({"kind": pymupdf.LINK_NAMED,
                          "from": pymupdf.Rect(180, 91, 196, 102),
                          "name": "cite.Smith20"})
    data = doc.tobytes()
    doc.close()
    return data


def _client(tmp_path):
    return TestClient(create_app(db_path=tmp_path / "papers.db"), base_url="http://127.0.0.1:8765")


def test_uploading_a_manuscript_returns_a_workspace_path(tmp_path):
    client = _client(tmp_path)

    body = client.post("/api/upload",
                       files={"file": ("paper.pdf", _pdf_bytes(), "application/pdf")}).json()

    assert body["path"].endswith("paper.pdf")
    assert body["name"] == "paper.pdf"
    assert body["reused"] is False


def test_uploading_the_same_paper_twice_reuses_its_workspace(tmp_path):
    """Content-hash keyed, so the library built the first time is still there."""
    client = _client(tmp_path)
    data = _pdf_bytes()

    first = client.post("/api/upload", files={"file": ("a.pdf", data, "application/pdf")}).json()
    second = client.post("/api/upload", files={"file": ("b.pdf", data, "application/pdf")}).json()

    assert first["path"] == second["path"]
    assert second["reused"] is True


def test_a_different_paper_gets_a_different_workspace(tmp_path):
    client = _client(tmp_path)
    one = client.post("/api/upload",
                      files={"file": ("a.pdf", _pdf_bytes(), "application/pdf")}).json()

    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72.0, 100.0), "Something else entirely [1]", fontsize=11)
    p.insert_link({"kind": pymupdf.LINK_NAMED,
                   "from": pymupdf.Rect(180, 91, 196, 102), "name": "cite.Other"})
    other = doc.tobytes(); doc.close()

    two = client.post("/api/upload",
                      files={"file": ("b.pdf", other, "application/pdf")}).json()

    assert one["path"] != two["path"]


def test_a_pdf_without_citation_links_is_refused_with_an_explanation(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/upload",
        files={"file": ("plain.pdf", _pdf_bytes(with_links=False), "application/pdf")},
    )

    assert response.status_code == 422
    assert "hyperref" in response.json()["detail"]


def test_a_non_pdf_is_refused(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/upload", files={"file": ("notes.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 415


def test_a_pdf_extension_on_a_non_pdf_is_still_refused(tmp_path):
    """Trusting the filename would let anything through."""
    client = _client(tmp_path)

    response = client.post(
        "/api/upload", files={"file": ("fake.pdf", b"not really", "application/pdf")}
    )

    assert response.status_code == 415


def test_a_refused_upload_leaves_nothing_behind(tmp_path):
    client = _client(tmp_path)
    client.post("/api/upload",
                files={"file": ("plain.pdf", _pdf_bytes(with_links=False), "application/pdf")})

    workspaces = tmp_path / "workspaces"
    leftovers = list(workspaces.rglob("*.pdf")) if workspaces.exists() else []
    assert leftovers == []


def test_an_uploaded_manuscript_opens_as_a_workspace(tmp_path):
    """Upload then open: the whole point."""
    client = _client(tmp_path)
    up = client.post("/api/upload",
                     files={"file": ("paper.pdf", _pdf_bytes(), "application/pdf")}).json()

    body = client.post("/api/workspace", json={"path": up["path"]}).json()

    assert body["pages"] == 1
    assert [r["key"] for r in body["references"]] == ["Smith20"]
    assert body["library_exists"] is False
