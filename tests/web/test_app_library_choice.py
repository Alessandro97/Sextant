"""Choosing where a manuscript's reference library lives.

Two papers were lost to Sextant deciding this silently: the library went into
a content-hashed folder under ~/.local/share while the user put files in the
refs/ folder beside their manuscript.
"""

import pymupdf
from starlette.testclient import TestClient

from sextant.manuscript.library import POINTER
from sextant.web.app import create_app


def _manuscript(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72.0, 100.0), "Claim here [1]", fontsize=11)
    page.insert_link({"kind": pymupdf.LINK_NAMED,
                      "from": pymupdf.Rect(120, 91, 136, 102), "name": "cite.K"})
    doc.save(path)
    doc.close()
    return path


def test_a_missing_library_asks_before_creating_anything(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace/library", json={"path": str(pdf)}).json()

    assert body["needs_confirmation"] is True
    assert body["refs_dir"] == str(tmp_path / "refs")
    assert not (tmp_path / "refs").exists(), "must not create until confirmed"


def test_confirming_creates_it_with_an_inbox(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace/library",
                       json={"path": str(pdf), "create": True}).json()

    assert body["exists"] is True
    assert (tmp_path / "refs").is_dir()
    assert (tmp_path / "refs" / "inbox").is_dir()


def test_an_existing_folder_needs_no_confirmation(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf")
    (tmp_path / "refs").mkdir()
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace/library", json={"path": str(pdf)}).json()

    assert body["needs_confirmation"] is False


def test_a_chosen_folder_elsewhere_is_remembered_and_used(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf")
    elsewhere = tmp_path / "shared-papers"
    elsewhere.mkdir()
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    client.post("/api/workspace/library",
                json={"path": str(pdf), "refs_dir": str(elsewhere)})
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert ws["refs_dir"] == str(elsewhere)
    # Kept with Sextant's own data: a pointer beside the manuscript is one a
    # folder someone sent can ship.
    assert not (tmp_path / POINTER).exists()
    assert str(pdf.resolve()) in (tmp_path / "libraries.json").read_text()


def test_the_whole_app_follows_the_chosen_folder(tmp_path):
    """Not just the workspace route -- adding a paper must land there too."""
    pdf = _manuscript(tmp_path / "m.pdf")
    elsewhere = tmp_path / "shared-papers"
    elsewhere.mkdir()
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    client.post("/api/workspace/library",
                json={"path": str(pdf), "refs_dir": str(elsewhere)})

    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), "Some Paper Title Here", fontsize=12)
    data = doc.tobytes()
    doc.close()
    client.post("/api/workspace/add", data={"path": str(pdf)},
                files={"files": ("x.pdf", data, "application/pdf")})

    assert (elsewhere / "inbox" / "x.pdf").exists()
    assert not (tmp_path / "refs").exists()


def test_pointing_at_a_file_instead_of_a_folder_is_refused(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf")
    (tmp_path / "notafolder").write_text("x")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.post("/api/workspace/library",
                           json={"path": str(pdf),
                                 "refs_dir": str(tmp_path / "notafolder")})

    assert response.status_code == 400
    assert "not a folder" in response.json()["detail"]


def _client(tmp_path):
    return TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")


def test_a_refs_folder_shipped_as_a_link_is_not_accepted(tmp_path):
    """refs/ -> ~/.bashrc.d: accepted as a folder, it was recorded resolved and
    written into as though it were the manuscript's own."""
    pdf = _manuscript(tmp_path / "m.pdf")
    startup = tmp_path / "home" / ".bashrc.d"
    startup.mkdir(parents=True)
    (tmp_path / "refs").symlink_to(startup)

    response = _client(tmp_path).post("/api/workspace/library",
                                      json={"path": str(pdf), "create": True})

    assert response.status_code == 400
    assert list(startup.iterdir()) == []


def test_a_dangling_link_is_not_followed_to_make_folders(tmp_path):
    """A link to somewhere that does not exist yet reads as not there, and
    making the library made folders wherever it pointed."""
    pdf = _manuscript(tmp_path / "m.pdf")
    nowhere = tmp_path / "home" / ".bashrc.d"
    (tmp_path / "home").mkdir()
    (tmp_path / "refs").symlink_to(nowhere)

    response = _client(tmp_path).post("/api/workspace/library",
                                      json={"path": str(pdf), "create": True})

    assert response.status_code == 400
    assert not nowhere.exists()
