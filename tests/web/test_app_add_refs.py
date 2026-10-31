"""Adding reference papers from the browser.

Before this route the only way in was to copy files into a content-hashed
folder under ~/.local/share, found through a file manager. A browser upload
sends bytes and a filename, never a path, so Sextant cannot see where the
user's own manuscript folder is -- which is exactly how two papers ended up
somewhere the app would never look.
"""

import pymupdf
from starlette.testclient import TestClient

from sextant.web.app import create_app


def _manuscript(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72.0, 100.0), "Many schemes exist [1]", fontsize=11)
    x = 72.0 + pymupdf.get_text_length("Many schemes exist ", fontsize=11)
    page.insert_link({"kind": pymupdf.LINK_NAMED,
                      "from": pymupdf.Rect(x, 91.0, x + 14.0, 102.0),
                      "name": "cite.Wanted"})
    doc.save(path)
    doc.close()
    return path


def _paper_bytes(title):
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), title, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


TITLE = "A Distinctive Paper About Layered Network Architectures"


def _project(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf")
    (tmp_path / "refs").mkdir()
    (tmp_path / "refs.bib").write_text(
        f"@article{{Wanted, title={{{TITLE}}}, year={{2021}}}}")
    return pdf


def test_a_paper_added_from_the_browser_is_matched_to_its_reference(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post(
        "/api/workspace/add",
        data={"path": str(pdf)},
        files={"files": ("whatever-the-publisher-called-it.pdf",
                         _paper_bytes(TITLE), "application/pdf")},
    ).json()

    assert [m["key"] for m in body["matched"]] == ["Wanted"]
    assert (tmp_path / "refs" / "Wanted.pdf").exists()


def test_the_publishers_filename_does_not_matter(tmp_path):
    """Matching is on the title inside the file, not what it is called."""
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post(
        "/api/workspace/add",
        data={"path": str(pdf)},
        files={"files": ("1-s2.0-S0140366421X00123-main.pdf",
                         _paper_bytes(TITLE), "application/pdf")},
    ).json()

    assert [m["key"] for m in body["matched"]] == ["Wanted"]


def test_a_paper_that_matches_nothing_is_reported_not_silently_kept(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post(
        "/api/workspace/add",
        data={"path": str(pdf)},
        files={"files": ("x.pdf", _paper_bytes("An Unrelated Study Of Bees"),
                         "application/pdf")},
    ).json()

    assert body["saved"] == ["x.pdf"]
    assert body["matched"] == []


def test_a_non_document_is_rejected_with_a_reason(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post(
        "/api/workspace/add",
        data={"path": str(pdf)},
        files={"files": ("notes.txt", b"hello", "text/plain")},
    ).json()

    assert body["saved"] == []
    assert body["rejected"][0]["name"] == "notes.txt"
    assert "not a PDF" in body["rejected"][0]["reason"]


def test_a_pdf_extension_on_something_else_is_rejected(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post(
        "/api/workspace/add",
        data={"path": str(pdf)},
        files={"files": ("fake.pdf", b"not really a pdf", "application/pdf")},
    ).json()

    assert body["rejected"][0]["reason"] == "not actually a PDF"


def test_several_papers_can_be_added_at_once(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post(
        "/api/workspace/add",
        data={"path": str(pdf)},
        files=[("files", ("a.pdf", _paper_bytes(TITLE), "application/pdf")),
               ("files", ("b.pdf", _paper_bytes("Something Else Entirely"),
                          "application/pdf"))],
    ).json()

    assert len(body["saved"]) == 2
    assert [m["key"] for m in body["matched"]] == ["Wanted"]


def test_a_filename_cannot_escape_the_inbox(tmp_path):
    """The filename comes from the browser and is not to be trusted."""
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    client.post(
        "/api/workspace/add",
        data={"path": str(pdf)},
        files={"files": ("../../escaped.pdf", _paper_bytes(TITLE),
                         "application/pdf")},
    )

    assert not (tmp_path.parent / "escaped.pdf").exists()
    assert not (tmp_path / "escaped.pdf").exists()


def test_a_file_can_be_filed_under_a_chosen_reference_directly(tmp_path):
    """Title matching is a convenience and will sometimes be wrong. When the
    reader knows which paper this is, they should not have to make the matcher
    agree."""
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post(
        "/api/workspace/assign",
        data={"path": str(pdf), "key": "Wanted"},
        files={"file": ("anything.pdf",
                        _paper_bytes("A Title That Matches Nothing At All"),
                        "application/pdf")},
    ).json()

    assert body["key"] == "Wanted"
    assert (tmp_path / "refs" / "Wanted.pdf").exists()


def test_assigning_makes_the_reference_available(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    client.post("/api/workspace/assign",
                data={"path": str(pdf), "key": "Wanted"},
                files={"file": ("x.pdf", _paper_bytes("Unrelated"),
                                "application/pdf")})

    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert next(r for r in ws["references"] if r["key"] == "Wanted")["available"]


def test_assigning_to_a_reference_the_manuscript_does_not_cite_is_a_404(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.post(
        "/api/workspace/assign",
        data={"path": str(pdf), "key": "NotCitedAnywhere"},
        files={"file": ("x.pdf", _paper_bytes("t"), "application/pdf")},
    )

    assert response.status_code == 404


def test_assigning_does_not_disturb_the_references_already_filed(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    client.post("/api/workspace/add", data={"path": str(pdf)},
                files={"files": ("a.pdf", _paper_bytes(TITLE), "application/pdf")})
    before = (tmp_path / "refs" / "Wanted.pdf").resolve().read_bytes()

    client.post("/api/workspace/assign",
                data={"path": str(pdf), "key": "Wanted"},
                files={"file": ("b.pdf", _paper_bytes("Replacement Paper"),
                                "application/pdf")})

    assert (tmp_path / "refs" / "Wanted.pdf").exists()
    after = (tmp_path / "refs" / "Wanted.pdf").resolve().read_bytes()
    assert after != before, "the chosen file should win"


def _victim(tmp_path):
    victim = tmp_path / "bashrc"
    victim.write_text("# the user's own\n")
    return victim


def test_adding_a_paper_does_not_write_through_a_link_in_the_inbox(tmp_path):
    """A folder someone sent can ship refs/inbox/paper.pdf as a link. The
    reader's own upload, by that name, went wherever it pointed."""
    pdf = _project(tmp_path)
    victim = _victim(tmp_path)
    (tmp_path / "refs" / "inbox").mkdir()
    (tmp_path / "refs" / "inbox" / "paper.pdf").symlink_to(victim)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    client.post("/api/workspace/add", data={"path": str(pdf)},
                files={"files": ("paper.pdf", _paper_bytes(TITLE), "application/pdf")})

    assert victim.read_text() == "# the user's own\n"


def test_assigning_a_paper_does_not_write_through_a_link_in_the_inbox(tmp_path):
    pdf = _project(tmp_path)
    victim = _victim(tmp_path)
    (tmp_path / "refs" / "inbox").mkdir()
    (tmp_path / "refs" / "inbox" / "paper.pdf").symlink_to(victim)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    client.post("/api/workspace/assign", data={"path": str(pdf), "key": "Wanted"},
                files={"file": ("paper.pdf", _paper_bytes(TITLE), "application/pdf")})

    assert victim.read_text() == "# the user's own\n"


def test_an_inbox_that_is_a_link_is_refused_with_a_reason(tmp_path):
    pdf = _project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "refs" / "inbox").symlink_to(elsewhere)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.post("/api/workspace/add", data={"path": str(pdf)},
                           files={"files": ("paper.pdf", _paper_bytes(TITLE),
                                            "application/pdf")})

    assert response.status_code == 400
    assert "symbolic link" in response.json()["detail"]
    assert list(elsewhere.iterdir()) == []
