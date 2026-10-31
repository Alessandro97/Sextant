import pymupdf
from starlette.testclient import TestClient

from sextant.web.app import create_app

TEX = r"""
Field trials report only $3$~Mbit/s per node~\cite{Good}.
Systems reach 99~GHz operation~\cite{Bad}.
"""


def _project(tmp_path):
    (tmp_path / "main.tex").write_text(TEX)
    refs = tmp_path / "refs"
    refs.mkdir()
    for key, body in (
        ("Good", "The measured peak was 3 Mbit/s per node."),
        ("Bad", "This paper is about medieval trade routes."),
    ):
        doc = pymupdf.open()
        doc.new_page().insert_text((72.0, 100.0), body, fontsize=11)
        doc.save(refs / f"{key}.pdf")
        doc.close()
    return tmp_path / "main.tex"


def test_audit_route_returns_findings(tmp_path):
    tex = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.get("/api/audit", params={"tex": str(tex)}).json()

    verdicts = {f["key"]: f["verdict"] for f in body["findings"]}
    assert verdicts["Good"] == "located"
    assert verdicts["Bad"] == "not-found"


def test_audit_route_reports_counts(tmp_path):
    tex = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.get("/api/audit", params={"tex": str(tex)}).json()

    assert body["counts"]["located"] == 1


def test_audit_on_a_missing_manuscript_is_a_404(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.get("/api/audit", params={"tex": str(tmp_path / "nope.tex")})

    assert response.status_code == 404


def test_a_located_finding_carries_what_the_viewer_needs_to_jump(tmp_path):
    """A finding is only clickable if it names a page and a quote to locate."""
    tex = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.get("/api/audit", params={"tex": str(tex)}).json()
    good = next(f for f in body["findings"] if f["key"] == "Good")

    assert good["span"]["page"] == 1
    assert good["excerpt"]


def test_a_finding_carries_the_store_id_of_the_cited_paper(tmp_path):
    """Joining on content hash is what makes a finding clickable. Title
    matching would break on the many papers whose title is unknown."""
    from sextant.store.db import Store

    tex = _project(tmp_path)
    db = tmp_path / "p.db"
    store = Store.open(db)
    adopted = store.adopt_pdf(tmp_path / "refs" / "Good.pdf", title="A Good Paper")
    store.close()

    client = TestClient(create_app(db_path=db), base_url="http://127.0.0.1:8765")
    body = client.get("/api/audit", params={"tex": str(tex)}).json()

    good = next(f for f in body["findings"] if f["key"] == "Good")
    bad = next(f for f in body["findings"] if f["key"] == "Bad")
    assert good["paper_id"] == adopted.id
    assert bad["paper_id"] is None


def test_paper_id_is_null_when_the_store_is_empty(tmp_path):
    tex = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.get("/api/audit", params={"tex": str(tex)}).json()

    assert all(f["paper_id"] is None for f in body["findings"])


def test_the_audit_route_reads_no_pdf_outside_refs(tmp_path):
    """\\cite{../outside} named a file beside refs/, and the route checked the
    claim against it."""
    ms = tmp_path / "ms"
    (ms / "refs").mkdir(parents=True)
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), "The measured peak was 3 Mbit/s per node.")
    doc.save(ms / "outside.pdf")
    doc.close()
    (ms / "main.tex").write_text("Trials report 3~Mbit/s per node~\\cite{../outside}.\n")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.get("/api/audit", params={"tex": str(ms / "main.tex")}).json()

    assert [f["verdict"] for f in body["findings"]] == ["no-source"]
