import pymupdf
import pytest
from starlette.testclient import TestClient

from sextant.chat import compose
from sextant.web.app import create_app


@pytest.fixture(autouse=True)
def never_shell_out(monkeypatch):
    """The suite must not invoke `claude -p`: it is slow and it is the user's
    subscription. Route tests exercise the copy path."""
    monkeypatch.setattr(compose, "cli_available", lambda: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _manuscript(path, entries):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 100.0
    for marker, key, claim in entries:
        page.insert_text((72.0, y), f"{claim} {marker}.", fontsize=11)
        width = pymupdf.get_text_length(f"{claim} ", fontsize=11)
        mwidth = pymupdf.get_text_length(marker, fontsize=11)
        page.insert_link({"kind": pymupdf.LINK_NAMED,
                          "from": pymupdf.Rect(72.0 + width, y - 9.0,
                                               72.0 + width + mwidth, y + 2.0),
                          "name": f"cite.{key}"})
        y += 24.0
    doc.save(path)
    doc.close()
    return path


def _cited(path, body):
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), body, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def _project(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [
        ("[1]", "Good", "Rates reach 3 Mbit/s"),
        ("[2]", "Gone", "The plume spans 50 km"),
    ])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Good.pdf", "Peak throughput was 3 Mbit/s overall.")
    return pdf


def test_opening_a_manuscript_returns_markers_and_a_scoped_library(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert body["pages"] == 1
    assert {m["key"] for m in body["markers"]} == {"Good", "Gone"}
    assert {r["key"] for r in body["references"]} == {"Good", "Gone"}


def test_markers_carry_their_status_and_a_display_box(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in body["markers"] if m["key"] == "Good")

    assert good["status"] == "verified"
    assert good["marker"] == "[1]"
    assert 0.0 <= good["box"]["left"] <= 1.0
    assert good["box"]["width"] > 0
    assert good["cited_page"] == 1


def test_an_unavailable_reference_is_reported_as_such(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace", json={"path": str(pdf)}).json()
    gone = next(r for r in body["references"] if r["key"] == "Gone")

    assert gone["available"] is False


def test_counts_are_reported_for_the_status_bar(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert body["counts"] == {"verified": 1, "no-source": 1}


def test_a_manuscript_without_citation_links_is_a_422(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), "plain text", fontsize=11)
    doc.save(tmp_path / "plain.pdf")
    doc.close()
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.post("/api/workspace", json={"path": str(tmp_path / "plain.pdf")})

    assert response.status_code == 422
    assert "hyperref" in response.json()["detail"]


def test_a_missing_path_is_a_404(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.post("/api/workspace", json={"path": str(tmp_path / "no.pdf")})

    assert response.status_code == 404


def test_the_manuscript_page_image_is_served(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.get("/api/workspace/page/1.png", params={"path": str(pdf)})

    assert response.status_code == 200
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_manuscript_page_past_the_end_is_a_404(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.get("/api/workspace/page/99.png", params={"path": str(pdf)})

    assert response.status_code == 404


def test_chat_without_a_backend_returns_a_prompt_to_copy(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/chat", json={
        "path": str(pdf), "question": "what throughput is reached?"
    }).json()

    assert body["mode"] == "copy"
    assert "3 Mbit/s" in body["prompt"]
    assert body["excerpts"]


def test_chat_can_target_a_reference_instead_of_the_manuscript(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/chat", json={
        "path": str(pdf), "key": "Good", "question": "what was the peak throughput?"
    }).json()

    assert "Peak throughput" in body["prompt"]
    assert body["target"] == "Good"


def test_chat_about_an_unavailable_reference_is_a_404(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.post("/api/chat", json={
        "path": str(pdf), "key": "Gone", "question": "anything?"
    })

    assert response.status_code == 404


def test_the_backends_route_reports_what_is_available(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.get("/api/backends").json()

    assert set(body) == {"cli", "api"}


def test_fetching_a_key_not_in_any_bib_says_so_rather_than_failing(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace/fetch", json={
        "path": str(pdf), "keys": ["Gone"], "offline": True
    }).json()

    (row,) = body["results"]
    assert row["key"] == "Gone"
    assert row["available"] is False
    assert ".bib" in row["reason"]


def test_fetching_resolves_a_key_that_is_in_the_bib(tmp_path):
    pdf = _project(tmp_path)
    (tmp_path / "refs.bib").write_text(
        "@article{Gone, title={A Findable Paper With A Long Title}, year={2020}}"
    )
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace/fetch", json={
        "path": str(pdf), "keys": ["Gone"], "offline": True
    }).json()

    (row,) = body["results"]
    assert row["key"] == "Gone"
    assert row["status"] in {"unresolved", "no-pdf", "resolved"}
    assert ".bib" not in row["reason"]


def test_a_fresh_manuscript_reports_every_reference_as_unattempted(tmp_path):
    """Nothing has been tried yet, so auto-build has work to do."""
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert body["missing"] == ["Gone"]
    assert body["unattempted"] == ["Gone"]


def test_after_a_fetch_nothing_is_unattempted_so_reopening_is_offline(tmp_path):
    """The property this exists for: some references never resolve, and retrying
    them on every open would hit the network forever.

    The bib entry matters. Without one the key reaches no resolver and so
    costs nothing to retry -- which is why it is no longer recorded, and why
    testing this property with a key that has no entry did not test it."""
    pdf = _project(tmp_path)
    (tmp_path / "refs.bib").write_text(
        '@article{Gone, title={Grazing Pressure on Rural Pastures}, '
        'doi={10.5555/EXAMPLE.1}}')
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    client.post("/api/workspace/fetch",
                json={"path": str(pdf), "keys": ["Gone"], "offline": True})
    body = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert body["missing"] == ["Gone"], "still missing, as expected"
    assert body["unattempted"] == [], "but must not be retried automatically"


def test_fetch_with_no_keys_targets_only_the_missing_ones(tmp_path):
    """Re-resolving a paper already in refs/ is wasted network and could
    replace a good file with a worse one."""
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace/fetch",
                       json={"path": str(pdf), "offline": True}).json()

    assert [r["key"] for r in body["results"]] == ["Gone"]


def test_a_manuscript_whose_library_is_complete_has_nothing_to_build(tmp_path):
    """Paste a PDF whose refs/ is already populated: no download at all."""
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Good.pdf", "Peak throughput was 3 Mbit/s overall.")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert body["missing"] == []
    assert body["unattempted"] == []
    assert body["library_exists"] is True
    assert body["counts"] == {"verified": 1}


def test_a_manuscript_with_no_refs_folder_says_the_library_does_not_exist(tmp_path):
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert body["library_exists"] is False
    assert body["unattempted"] == ["Good"]


def test_update_adopts_a_pdf_dropped_straight_into_the_refs_folder(tmp_path):
    """The escape hatch: paywalled or portal-blocked papers get added by hand."""
    pdf = _project(tmp_path)
    (tmp_path / "refs.bib").write_text(
        "@article{Gone, title={Seasonal Analysis Of Upland Grazing Records}, year={2020}}"
    )
    dropped = tmp_path / "refs" / "whatever-the-browser-called-it.pdf"
    _cited(dropped, "Seasonal Analysis Of Upland Grazing Records")

    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    body = client.post("/api/workspace/rescan", json={"path": str(pdf)}).json()

    assert [m["key"] for m in body["matched"]] == ["Gone"]
    assert (tmp_path / "refs" / "Gone.pdf").exists()


def test_update_also_looks_in_the_inbox(tmp_path):
    pdf = _project(tmp_path)
    (tmp_path / "refs.bib").write_text(
        "@article{Gone, title={Seasonal Analysis Of Upland Grazing Records}, year={2020}}"
    )
    inbox = tmp_path / "refs" / "inbox"; inbox.mkdir(parents=True, exist_ok=True)
    _cited(inbox / "download.pdf", "Seasonal Analysis Of Upland Grazing Records")

    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    body = client.post("/api/workspace/rescan", json={"path": str(pdf)}).json()

    assert [m["key"] for m in body["matched"]] == ["Gone"]


def test_update_reports_what_is_still_missing(tmp_path):
    pdf = _project(tmp_path)

    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    body = client.post("/api/workspace/rescan", json={"path": str(pdf)}).json()

    assert body["matched"] == []
    assert body["still_missing"] == ["Gone"]


def test_update_does_not_disturb_references_already_present(tmp_path):
    """Good.pdf must survive a rescan intact."""
    pdf = _project(tmp_path)
    before = (tmp_path / "refs" / "Good.pdf").read_bytes()

    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    client.post("/api/workspace/rescan", json={"path": str(pdf)})

    good = tmp_path / "refs" / "Good.pdf"
    assert good.exists()
    assert good.read_bytes() == before


def test_update_never_matches_an_unrelated_pdf_to_a_reference(tmp_path):
    """Filing a paper under the wrong key produces a confident verdict about
    the wrong document. Report, never guess."""
    pdf = _project(tmp_path)
    (tmp_path / "refs.bib").write_text(
        "@article{Gone, title={Seasonal Analysis Of Upland Grazing Records}, year={2020}}"
    )
    _cited(tmp_path / "refs" / "random.pdf", "An Entirely Unrelated Study Of Bees")

    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    body = client.post("/api/workspace/rescan", json={"path": str(pdf)}).json()

    assert body["matched"] == []
    assert body["still_missing"] == ["Gone"]


def test_the_rescan_leaves_no_scratch_directory_behind(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    client.post("/api/workspace/rescan", json={"path": str(pdf)})

    assert not (tmp_path / "refs" / ".loose").exists()


def test_assessing_a_marker_returns_a_verdict_and_passages(tmp_path, monkeypatch):
    from sextant.web import app as app_module

    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: "VERDICT: related\nWHY: on topic (p. 1)")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    body = client.post("/api/assess",
                       json={"path": str(pdf), "marker_id": good["id"]}).json()

    assert body["verdict"] == "related"
    assert body["key"] == "Good"
    assert body["excerpts"]


def test_assessing_a_marker_with_no_local_source_is_a_404(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    gone = next(m for m in ws["markers"] if m["key"] == "Gone")

    response = client.post("/api/assess",
                           json={"path": str(pdf), "marker_id": gone["id"]})

    assert response.status_code == 404


def test_assessing_an_unknown_marker_is_a_404(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.post("/api/assess", json={"path": str(pdf), "marker_id": 999})

    assert response.status_code == 404


def test_every_aligned_passage_carries_its_own_highlight(tmp_path, monkeypatch):
    """A passage the reader cannot see in place is only an assertion about the
    paper. Each one needs a page and boxes, not just the best."""
    from sextant.web import app as app_module

    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: "VERDICT: related\nWHY: on topic (p. 1)")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    body = client.post("/api/assess",
                       json={"path": str(pdf), "marker_id": good["id"]}).json()

    assert body["excerpts"], "expected at least one aligned passage"
    for row in body["excerpts"]:
        assert "boxes" in row, "every passage needs geometry"
        assert row["page"] >= 1
    located = [r for r in body["excerpts"] if r["boxes"]]
    assert located, "at least one passage should be locatable in the source"
    for box in located[0]["boxes"]:
        assert 0.0 <= box["left"] <= 1.0 and 0.0 <= box["top"] <= 1.0


def test_the_workspace_says_where_its_library_folder_is(tmp_path):
    """Upload puts the folder under the store, which is nowhere anyone would
    guess. Not saying so cost a user a misplaced file."""
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert body["refs_dir"] == str(tmp_path / "refs")


def test_a_non_pdf_in_the_refs_folder_is_reported_not_ignored(tmp_path):
    """A .doc used to be invisible: the glob skipped it and nothing said why."""
    pdf = _project(tmp_path)
    (tmp_path / "refs" / "23501-h30.doc").write_bytes(b"not really a doc")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    body = client.post("/api/workspace", json={"path": str(pdf)}).json()

    assert "23501-h30.doc" in body["unconverted"]


def _twice(path):
    """One reference cited twice, for two different quantities."""
    doc = pymupdf.open()
    page = doc.new_page()
    for y, claim, marker in ((100.0, "Rates reach 3 Mbit/s", "[1]"),
                             (140.0, "The plume spans 50 km", "[1]")):
        page.insert_text((72.0, y), f"{claim} {marker}.", fontsize=11)
        x = 72.0 + pymupdf.get_text_length(f"{claim} ", fontsize=11)
        page.insert_link({"kind": pymupdf.LINK_NAMED,
                          "from": pymupdf.Rect(x, y - 9.0, x + 14.0, y + 2.0),
                          "name": "cite.Both"})
    doc.save(path)
    doc.close()
    return path


def test_occurrences_lists_every_place_the_quantity_appears(tmp_path):
    pdf = _twice(tmp_path / "m.pdf")
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Both.pdf", "We saw 3 Mbit/s early and 3 Mbit/s again later.")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    first = ws["markers"][0]["id"]

    body = client.post("/api/marker/occurrences",
                       json={"path": str(pdf), "marker_id": first}).json()

    assert body["total"] == 2, "both occurrences, not just the first"
    assert body["highlights"], "and each one is highlightable"
    assert len(body["occurrences"]) == 2


def test_occurrences_lists_the_other_citations_of_the_same_reference(tmp_path):
    """A work cited nine times is nine separate claims."""
    pdf = _twice(tmp_path / "m.pdf")
    refs = tmp_path / "refs"; refs.mkdir()
    _cited(refs / "Both.pdf", "We saw 3 Mbit/s over 50 km.")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()

    body = client.post("/api/marker/occurrences",
                       json={"path": str(pdf), "marker_id": ws["markers"][1]["id"]}).json()

    assert len(body["siblings"]) == 2
    assert body["position"] == 1, "and where we are in that run"
    assert {s["claim"] for s in body["siblings"]} == {
        "Rates reach 3 Mbit/s.", "The plume spans 50 km."}, \
        "each claim is its own whole sentence"


def test_occurrences_is_empty_when_the_paper_is_not_available(tmp_path):
    pdf = _twice(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()

    body = client.post("/api/marker/occurrences",
                       json={"path": str(pdf), "marker_id": ws["markers"][0]["id"]}).json()

    assert body["highlights"] == {} and body["total"] == 0
    assert len(body["siblings"]) == 2, "siblings still listed"


def test_an_unknown_marker_is_a_404_for_occurrences(tmp_path):
    pdf = _twice(tmp_path / "m.pdf")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")

    response = client.post("/api/marker/occurrences",
                           json={"path": str(pdf), "marker_id": 999})

    assert response.status_code == 404


def test_opening_a_marker_never_silently_starts_a_model_call(tmp_path, monkeypatch):
    """The panel asks for a judgement when it opens. If that could trigger a
    twenty-second call, every click would cost one."""
    from sextant.web import app as app_module

    called = []
    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: called.append(p) or "VERDICT: related\nWHY: x")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    body = client.post("/api/assess", json={
        "path": str(pdf), "marker_id": good["id"], "only_ready": True}).json()

    assert body["pending"] is True
    assert called == [], "must not have asked Claude"


def test_a_precomputed_judgement_is_served_without_asking_again(tmp_path, monkeypatch):
    from sextant.web import app as app_module

    calls = []
    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: calls.append(p) or "VERDICT: supports\nWHY: y")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"]})
    again = client.post("/api/assess", json={
        "path": str(pdf), "marker_id": good["id"], "only_ready": True}).json()

    assert again["precomputed"] is True
    assert len(calls) == 1, "the second request must not reach the model"


def test_a_short_claim_is_retrieved_on_its_wider_context(tmp_path, monkeypatch):
    """A trimmed sentence can carry too few terms to match on. The query
    widens; the sentence being judged does not."""
    from sextant.web import app as app_module

    seen = []
    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: seen.append(p) or "VERDICT: related\nWHY: x")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"]})

    assert seen, "the model should have been asked"
    assert good["claim"] in seen[0], "the judged sentence is still the claim"


def test_the_summary_groups_scores_by_reference(tmp_path, monkeypatch):
    """A work cited nine times has nine judgements and the list has room for
    one figure."""
    from sextant.web import app as app_module

    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: "VERDICT: supports\nSCORE: 4\nWHY: yes")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")
    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"]})

    body = client.get("/api/assess/summary", params={"path": str(pdf)}).json()

    assert body["scores"]["Good"] == {"low": 4, "high": 4, "n": 1, "revised": False}
    assert body["revised"] == {}, "nobody argued for this one"


def test_a_reference_with_no_judgement_yet_has_no_score(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    client.post("/api/workspace", json={"path": str(pdf)})

    body = client.get("/api/assess/summary", params={"path": str(pdf)}).json()

    assert body["scores"] == {}


def test_an_unscored_verdict_does_not_become_a_zero(tmp_path, monkeypatch):
    """A withheld score means "no score", and zero means "remove this"."""
    from sextant.web import app as app_module

    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: "VERDICT: unclear\nSCORE: -1\nWHY: wrong pages")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")
    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"]})

    body = client.get("/api/assess/summary", params={"path": str(pdf)}).json()

    assert "Good" not in body["scores"]


def test_every_citation_with_a_source_is_assessed(tmp_path, monkeypatch):
    """A located figure is not proof: a survey can contain "21 GHz" in a
    passage unrelated to the sentence citing it. Verified markers earn a
    judgement too."""
    from sextant.web import app as app_module

    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: "VERDICT: supports\nSCORE: 4\nWHY: yes")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    verified = [m for m in ws["markers"] if m["status"] == "verified"]
    assert verified, "the fixture should have a verified marker"

    started = client.post("/api/assess/all", json={"path": str(pdf)}).json()

    available = {r["key"] for r in ws["references"] if r["available"]}
    expected = sum(1 for m in ws["markers"] if m["key"] in available)
    assert started["total"] == expected


def test_the_prompt_is_told_what_the_figure_check_found(tmp_path, monkeypatch):
    from sextant.web import app as app_module

    seen = []
    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: seen.append(p) or "VERDICT: supports\nSCORE: 5\nWHY: y")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["status"] == "verified")

    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"]})

    assert "ALREADY CHECKED" in seen[0]
    assert "was located on p." in seen[0]
    assert "for you to judge" in seen[0], "a located figure is evidence, not proof"


def test_a_missing_figure_is_reported_to_the_prompt_too(tmp_path, monkeypatch):
    from sextant.web import app as app_module

    seen = []
    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: seen.append(p) or "VERDICT: unrelated\nSCORE: 1\nWHY: n")
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Bad", "Sampling rates reach 99 GHz")])
    refs = tmp_path / "refs"; refs.mkdir()
    # Shares vocabulary so retrieval returns something; without excerpts the
    # model is never asked and the finding would go nowhere.
    _cited(refs / "Bad.pdf", "Sampling rates in this system are modest.")
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()

    client.post("/api/assess", json={"path": str(pdf), "marker_id": ws["markers"][0]["id"]})

    assert "does not appear anywhere in the cited paper" in seen[0]


def test_a_note_forces_a_fresh_judgement(tmp_path, monkeypatch):
    """The cached answer was reached without the author's argument, so it is
    not an answer to the question being asked."""
    from sextant.web import app as app_module

    prompts = []
    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: prompts.append(p) or "VERDICT: supports\nSCORE: 5\nWHY: fair")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"]})
    body = client.post("/api/assess", json={
        "path": str(pdf), "marker_id": good["id"],
        "note": "It is the standard reference for this method.",
    }).json()

    assert len(prompts) == 2, "the note must not be answered from cache"
    assert "THE AUTHOR ARGUES" in prompts[1]
    assert "standard reference for this method" in prompts[1]
    assert body["revised"] is True
    assert body["note"] == "It is the standard reference for this method."


def test_a_revised_judgement_replaces_the_cached_one(tmp_path, monkeypatch):
    from sextant.web import app as app_module

    replies = iter(["VERDICT: related\nSCORE: 2\nWHY: thin",
                    "VERDICT: supports\nSCORE: 4\nWHY: the note explains it"])
    monkeypatch.setattr(app_module, "ask_cli", lambda p: next(replies))
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"]})
    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"],
                                     "note": "context you lack"})
    again = client.post("/api/assess", json={
        "path": str(pdf), "marker_id": good["id"], "only_ready": True}).json()

    assert again["score"] == 4
    summary = client.get("/api/assess/summary", params={"path": str(pdf)}).json()
    assert summary["scores"]["Good"]["high"] == 4


def test_an_empty_note_is_not_a_revision(tmp_path, monkeypatch):
    from sextant.web import app as app_module

    calls = []
    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: calls.append(p) or "VERDICT: supports\nSCORE: 3\nWHY: x")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"]})
    body = client.post("/api/assess", json={"path": str(pdf),
                                            "marker_id": good["id"], "note": "   "}).json()

    assert len(calls) == 1, "whitespace is not an argument"
    assert body["precomputed"] is True


def test_the_summary_reports_a_score_per_citation_too(tmp_path, monkeypatch):
    """A work cited nine times has nine judgements, and the list of where it
    appears is exactly where they differ."""
    from sextant.web import app as app_module

    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: "VERDICT: supports\nSCORE: 4\nWHY: yes")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")
    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"]})

    body = client.get("/api/assess/summary", params={"path": str(pdf)}).json()

    assert body["by_marker"][str(good["id"])] == 4


def test_reset_discards_settled_judgements(tmp_path, monkeypatch):
    """Pressing Re-assess must throw verdicts away, not skip them as done.

    Judgements are opinions: the prompt and the retrieval both change, and a
    reader who has just fixed a sentence wants it looked at again."""
    from sextant.web import app as app_module

    replies = iter(["VERDICT: related\nSCORE: 3\nWHY: first",
                    "VERDICT: supports\nSCORE: 5\nWHY: second"])
    monkeypatch.setattr(app_module, "ask_cli", lambda p: next(replies))
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    first = client.post("/api/assess",
                        json={"path": str(pdf), "marker_id": good["id"]}).json()
    assert first["verdict"] == "related"

    assert client.post("/api/assess/reset",
                       json={"path": str(pdf)}).status_code == 200

    second = client.post("/api/assess",
                         json={"path": str(pdf), "marker_id": good["id"]}).json()
    assert second["verdict"] == "supports"


def test_an_argued_score_is_marked_and_can_be_taken_back(tmp_path, monkeypatch):
    """A revision replaces the judgement of record, so the list has to say the
    score was argued for -- and there has to be a way back that does not
    discard every other judgement in the manuscript."""
    from sextant.web import app as app_module

    def answer(prompt):
        return ("VERDICT: supports\nSCORE: 5\nWHY: the note settles it"
                if "ARGUED-HERE" in prompt
                else "VERDICT: supports\nSCORE: 2\nWHY: thin")

    monkeypatch.setattr(app_module, "ask_cli", answer)
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")
    here = {"path": str(pdf), "marker_id": good["id"]}

    client.post("/api/assess", json=here)
    body = client.get("/api/assess/summary", params={"path": str(pdf)}).json()
    assert body["scores"]["Good"]["high"] == 2
    assert body["scores"]["Good"]["revised"] is False

    revised = client.post("/api/assess", json={**here, "note": "ARGUED-HERE"}).json()
    assert revised["score"] == 5 and revised["revised"] is True

    body = client.get("/api/assess/summary", params={"path": str(pdf)}).json()
    assert body["scores"]["Good"]["high"] == 5
    assert body["scores"]["Good"]["revised"] is True, "the list must say it was argued"
    assert body["revised"] == {str(good["id"]): True}

    restored = client.post("/api/assess/revert", json=here)
    assert restored.status_code == 200
    assert restored.json()["score"] == 2, "the judgement that was displaced, exactly"

    body = client.get("/api/assess/summary", params={"path": str(pdf)}).json()
    assert body["scores"]["Good"]["high"] == 2
    assert body["scores"]["Good"]["revised"] is False
    assert body["revised"] == {}

    assert client.post("/api/assess/revert", json=here).status_code == 404


def test_the_model_is_given_the_whole_cited_paper(tmp_path, monkeypatch):
    """Retrieval used to choose what the model could see, so a citation could
    be reported unsupported because the sentence carrying it lost a keyword
    race. The distinctive phrase below shares nothing with the claim and would
    never be retrieved; it must reach the model anyway."""
    from sextant.web import app as app_module

    seen = {}

    def answer(prompt):
        seen["prompt"] = prompt
        return "VERDICT: supports\nSCORE: 4\nWHY: stated\nQUOTE: NONE"

    monkeypatch.setattr(app_module, "ask_cli", answer)

    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Peak throughput was 3 Mbit/s overall.",
                               fontsize=11)
    doc.new_page().insert_text((72, 100), "ZUCCHINI CALIBRATION APPENDIX.",
                               fontsize=11)
    doc.save(refs / "Good.pdf"); doc.close()

    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")
    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"],
                                     "effort": "high"})

    assert "ZUCCHINI CALIBRATION" in seen["prompt"], (
        "a page with no keyword overlap never reached the model"
    )
    assert "IN FULL" in seen["prompt"]


def _effort_prompt(tmp_path, monkeypatch, effort):
    """Assess one citation at `effort` and return the prompt the model saw."""
    from sextant.web import app as app_module
    seen = {}
    monkeypatch.setattr(app_module, "ask_cli", lambda p: seen.setdefault("p", p)
                        and "VERDICT: related\nSCORE: 2\nWHY: x\nQUOTE: NONE"
                        or "VERDICT: related\nSCORE: 2\nWHY: x\nQUOTE: NONE")
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Peak throughput was 3 Mbit/s overall.",
                               fontsize=11)
    doc.new_page().insert_text((72, 100), "ZUCCHINI CALIBRATION APPENDIX.", fontsize=11)
    doc.save(refs / "Good.pdf"); doc.close()
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")
    client.post("/api/assess", json={"path": str(pdf), "marker_id": good["id"],
                                     "effort": effort})
    return seen["p"]


def test_low_effort_sends_excerpts_not_the_paper(tmp_path, monkeypatch):
    """Thirty citations at high effort is about 350,000 tokens. Low is the
    setting for a first sweep, and it must actually be cheap."""
    prompt = _effort_prompt(tmp_path, monkeypatch, "low")

    assert "keyword overlap" in prompt
    assert "IN FULL" not in prompt


def test_high_effort_sends_the_paper(tmp_path, monkeypatch):
    prompt = _effort_prompt(tmp_path, monkeypatch, "high")

    assert "IN FULL" in prompt
    assert "ZUCCHINI CALIBRATION" in prompt


def test_an_unknown_effort_falls_back_rather_than_failing(tmp_path, monkeypatch):
    """A stale client sending something else gets the default, not a 500."""
    prompt = _effort_prompt(tmp_path, monkeypatch, "extreme")

    assert prompt, "the assessment still ran"


def test_reset_discards_without_starting_a_new_run(tmp_path, monkeypatch):
    """It used to clear and immediately re-run, so clearing one stale
    judgement committed you to paying for every other citation."""
    from sextant.web import app as app_module

    calls = []
    monkeypatch.setattr(app_module, "ask_cli",
                        lambda p: calls.append(p) or "VERDICT: related\nSCORE: 2\n"
                                                     "WHY: x\nQUOTE: NONE")
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    client.post("/api/workspace", json={"path": str(pdf)})

    body = client.post("/api/assess/reset", json={"path": str(pdf)}).json()

    assert body["running"] is False
    assert calls == [], "reset must not spend anything"
    assert body["total"] >= 1, "but it reports what is there to assess"


def test_the_closest_passages_are_found_without_a_model(tmp_path, monkeypatch):
    """A citation carrying no quantity has nothing for the mechanical screen,
    so before this the card could only say that nothing had looked. Term
    overlap costs nothing and can at least point at a page."""
    from sextant.web import app as app_module

    def boom(prompt):
        raise AssertionError("a model was called on the free path")

    monkeypatch.setattr(app_module, "ask_cli", boom)

    pdf = _manuscript(tmp_path / "m.pdf",
                      [("[1]", "Good", "Isotope dilution correction at the inlet")])
    refs = tmp_path / "refs"; refs.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_text((60, 90), "Abstract. A measurement study.", fontsize=10)
    doc.new_page().insert_text(
        (60, 90), "Isotope dilution correction is applied at the inlet.", fontsize=10)
    doc.save(refs / "Good.pdf"); doc.close()

    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    good = next(m for m in ws["markers"] if m["key"] == "Good")

    body = client.post("/api/marker/passages",
                       json={"path": str(pdf), "marker_id": good["id"]}).json()

    assert body["passages"], "a passage should have been found"
    assert any("Isotope" in p["text"] for p in body["passages"])
    # every returned passage was located in the page layout before being drawn
    assert all(p["boxes"] for p in body["passages"] if "Isotope" in p["text"])


def test_a_reference_with_no_pdf_yields_no_passages(tmp_path):
    pdf = _project(tmp_path)
    client = TestClient(create_app(db_path=tmp_path / "p.db"), base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()
    gone = next(m for m in ws["markers"] if m["key"] == "Gone")

    body = client.post("/api/marker/passages",
                       json={"path": str(pdf), "marker_id": gone["id"]}).json()

    assert body["passages"] == [] and body["highlights"] == {}


def test_a_quote_is_shown_only_as_far_as_it_was_located(tmp_path, monkeypatch):
    """Only the first 200 characters of a quote are located. Showing the rest
    beside those boxes presented text no one had found in the paper -- here a
    figure the paper never gives."""
    from sextant.web import app as app_module

    real = ("Peak throughput was 3 Mbit/s overall in the field trial, measured "
            "over a single node with a 5 MHz sampling clock and a standard client, and "
            "the error budget closed with a margin of a few percent at the edge "
            "of the cluster during every run of the benchmark suite.")
    invented = " Every later trial reached 900 Gbit/s on the same node."
    monkeypatch.setattr(app_module, "ask_cli", lambda p: (
        "VERDICT: related\nWHY: on topic (p. 1)\n"
        f"QUOTE: <p. 1> {real}{invented}"))
    pdf = _manuscript(tmp_path / "m.pdf", [("[1]", "Good", "Rates reach 3 Mbit/s")])
    refs = tmp_path / "refs"; refs.mkdir()
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 520, 400), real, fontsize=10)
    doc.save(refs / "Good.pdf")
    doc.close()
    client = TestClient(create_app(db_path=tmp_path / "p.db"),
                        base_url="http://127.0.0.1:8765")
    ws = client.post("/api/workspace", json={"path": str(pdf)}).json()

    body = client.post("/api/assess",
                       json={"path": str(pdf), "marker_id": ws["markers"][0]["id"]}).json()

    assert body["quotes"], "the real part of the quote should still be located"
    for quote in body["quotes"]:
        assert "900 Gbit/s" not in quote["text"]
        assert quote["text"].startswith("Peak throughput was 3 Mbit/s")
        # Cut short, and saying so: it stopped mid-sentence with no mark.
        assert quote["text"].endswith("…")
