"""Which dropped documents get converted, and which are left alone.

Conversion is the expensive step -- a large specification is tens of
seconds -- so the reader chooses. `to_pdf` is stubbed here: what is under test
is the choosing, not LibreOffice.
"""

from pathlib import Path

from sextant.refs import pipeline

NAMES = ["alpha.rtf", "beta.rtf", "gamma.rtf"]


def _folder(tmp_path: Path) -> Path:
    for name in NAMES:
        (tmp_path / name).write_text(r"{\rtf1\ansi body}")
    return tmp_path


def _stub_conversion(monkeypatch) -> list[str]:
    """Record what would have been converted, and convert nothing."""
    seen: list[str] = []

    def fake(source, out_dir):
        seen.append(Path(source).name)
        return Path(out_dir) / f"{Path(source).stem}.pdf"

    monkeypatch.setattr(pipeline, "to_pdf", fake)
    return seen


def test_only_the_named_documents_are_converted(tmp_path, monkeypatch):
    seen = _stub_conversion(monkeypatch)

    results = pipeline.convert_dropped_documents(_folder(tmp_path), only=["beta.rtf"])

    assert seen == ["beta.rtf"], "the other two were never touched"
    assert [r["source"] for r in results] == ["beta.rtf"]


def test_selecting_nothing_converts_nothing(tmp_path, monkeypatch):
    """An empty selection is a decision, not a missing one."""
    seen = _stub_conversion(monkeypatch)

    assert pipeline.convert_dropped_documents(_folder(tmp_path), only=[]) == []
    assert seen == []


def test_omitting_the_selection_still_converts_everything(tmp_path, monkeypatch):
    """"Update from folder" sends no selection and must keep its old behaviour:
    sweep the whole folder."""
    seen = _stub_conversion(monkeypatch)

    pipeline.convert_dropped_documents(_folder(tmp_path))

    assert sorted(seen) == NAMES


def test_a_converted_document_stops_being_pending(tmp_path, monkeypatch):
    """The notice never went away: it listed every office document in the
    folder, converted or not, so a reader who converted one saw the same list
    come back and concluded nothing had happened."""
    _stub_conversion(monkeypatch)
    folder = _folder(tmp_path)
    inbox = folder / "inbox"; inbox.mkdir()

    assert {p.name for p in pipeline.pending_conversions(folder)} == set(NAMES)

    (inbox / "beta.pdf").write_bytes(b"%PDF-1.7 converted")

    assert {p.name for p in pipeline.pending_conversions(folder)} == {"alpha.rtf", "gamma.rtf"}


def test_a_stale_conversion_is_still_pending(tmp_path, monkeypatch):
    """An edit after the conversion means the PDF no longer represents it."""
    import os, time
    _stub_conversion(monkeypatch)
    folder = _folder(tmp_path)
    inbox = folder / "inbox"; inbox.mkdir()
    (inbox / "beta.pdf").write_bytes(b"%PDF-1.7 old")
    old = time.time() - 100
    os.utime(inbox / "beta.pdf", (old, old))

    assert "beta.rtf" in {p.name for p in pipeline.pending_conversions(folder)}


def test_rescanning_a_folder_honours_the_selection(tmp_path, monkeypatch):
    """rescan_folder converted everything on its own, which undid the choice
    the route had just made -- pick one large specification, get all four."""
    seen = _stub_conversion(monkeypatch)

    pipeline.rescan_folder(_folder(tmp_path), [], convert_only=["beta.rtf"])

    assert seen == ["beta.rtf"]


def test_rescanning_with_no_selection_still_sweeps_everything(tmp_path, monkeypatch):
    seen = _stub_conversion(monkeypatch)

    pipeline.rescan_folder(_folder(tmp_path), [])

    assert sorted(seen) == NAMES


def test_adding_one_document_does_not_convert_the_others(tmp_path, monkeypatch):
    """Add papers swept the whole folder: adding a single PDF sat through the
    conversion of every office document already sitting there."""
    seen = _stub_conversion(monkeypatch)
    folder = _folder(tmp_path)
    (folder / "just-added.rtf").write_text(r"{\rtf1\ansi new}")

    pipeline.convert_dropped_documents(folder, only=["just-added.rtf", "some.pdf"])

    assert seen == ["just-added.rtf"], "the three already in the folder were left alone"


def test_a_pdf_bibliography_is_keyed_by_the_manuscript_citation_keys(
        tmp_path, latex_like_manuscript):
    """The fetch route looks entries up by the key the reader clicked, which
    hyperref supplies as "4821377". Keying the fallback bibliography by its
    printed labels -- "1" to "6" -- made every lookup miss: nothing was
    selected, every reference was reported "not in any .bib file near the
    manuscript", and arXiv was never contacted for papers sitting on arXiv.
    """
    from sextant.refs.pipeline import load_entries

    entries = load_entries(latex_like_manuscript(tmp_path / "m.pdf"))

    assert "4821377" in entries, f"keyed by label instead: {sorted(entries)}"
    assert "lopez2022survey" in entries, "a non-numeric key must join too"
    assert entries["4821377"].title, "the entry must still carry its metadata"
    assert entries["4821377"].key == "4821377", "the entry reports the label's key"
