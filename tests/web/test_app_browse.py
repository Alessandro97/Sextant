"""Picking a manuscript by its real path.

A browser file picker hands over bytes and a filename, never a directory, so
a file chosen that way cannot tell Sextant where the manuscript lives. The
server runs on the same machine and can.
"""

from starlette.testclient import TestClient

from sextant.web.app import create_app


def _client(tmp_path):
    return TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")


def test_listing_shows_folders_and_pdfs(tmp_path):
    (tmp_path / "papers").mkdir()
    (tmp_path / "main.pdf").write_bytes(b"%PDF")
    (tmp_path / "notes.txt").write_text("x")

    body = _client(tmp_path).get("/api/browse", params={"dir": str(tmp_path)}).json()

    kinds = {e["name"]: e["kind"] for e in body["entries"]}
    assert kinds == {"papers": "dir", "main.pdf": "pdf"}, "text files are noise here"


def test_folders_are_listed_before_documents(tmp_path):
    (tmp_path / "zzz-folder").mkdir()
    (tmp_path / "aaa.pdf").write_bytes(b"%PDF")

    entries = _client(tmp_path).get(
        "/api/browse", params={"dir": str(tmp_path)}).json()["entries"]

    assert [e["kind"] for e in entries] == ["dir", "pdf"]


def test_every_entry_carries_a_real_absolute_path(tmp_path):
    """The whole point: the path is what the browser cannot provide."""
    (tmp_path / "main.pdf").write_bytes(b"%PDF")

    body = _client(tmp_path).get("/api/browse", params={"dir": str(tmp_path)}).json()

    assert body["entries"][0]["path"] == str(tmp_path / "main.pdf")


def test_the_parent_is_offered_for_navigating_up(tmp_path):
    (tmp_path / "sub").mkdir()

    body = _client(tmp_path).get(
        "/api/browse", params={"dir": str(tmp_path / "sub")}).json()

    assert body["parent"] == str(tmp_path)


def test_hidden_entries_are_left_out(tmp_path):
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".secret.pdf").write_bytes(b"%PDF")

    body = _client(tmp_path).get("/api/browse", params={"dir": str(tmp_path)}).json()

    assert body["entries"] == []


def test_no_argument_starts_at_home(tmp_path):
    from pathlib import Path

    body = _client(tmp_path).get("/api/browse").json()

    assert body["dir"] == str(Path.home())


def test_a_missing_folder_is_a_404(tmp_path):
    response = _client(tmp_path).get("/api/browse",
                                     params={"dir": str(tmp_path / "nope")})

    assert response.status_code == 404
