"""A project folder someone else made cannot steer Sextant's writes.

Each test is an attack the security audit ran, through the real entry point:
a link shipped in refs/, under the name Sextant is about to write.
"""

import subprocess

import pytest

from sextant.refs.folder import materialize
from sextant.refs.models import Resolution
from sextant.safefs import UnsafePathError


@pytest.fixture
def victim(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bashrc = home / ".bashrc"
    bashrc.write_text("# the user's own\n")
    return bashrc


def _refs(tmp_path):
    refs = tmp_path / "project" / "refs"
    refs.mkdir(parents=True)
    return refs


def test_a_shipped_missing_md_link_does_not_become_the_report(tmp_path, victim):
    refs = _refs(tmp_path)
    (refs / "MISSING.md").symlink_to(victim)

    materialize([Resolution(key="evil", status="unresolved",
                            title='Wetlands; touch "$HOME/PWNED"; #')], refs)

    assert victim.read_text() == "# the user's own\n"
    assert "Wetlands" in (refs / "MISSING.md").read_text()


def test_a_refs_folder_that_is_a_link_is_not_written_into(tmp_path):
    startup = tmp_path / "home" / ".bashrc.d"
    startup.mkdir(parents=True)
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "refs").symlink_to(startup)

    with pytest.raises(UnsafePathError):
        materialize([Resolution(key="evil", status="unresolved")],
                    tmp_path / "project" / "refs")

    assert list(startup.iterdir()) == []


@pytest.mark.parametrize("folder", ["inbox", ".downloads"])
def test_a_shipped_link_in_place_of_a_working_folder_is_refused(tmp_path, folder):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    refs = _refs(tmp_path)
    (refs / folder).symlink_to(elsewhere)

    with pytest.raises(UnsafePathError):
        materialize([], refs)


def test_the_attempts_file_is_not_written_through_a_link(tmp_path, victim):
    from sextant.refs.pipeline import ATTEMPTS_FILE, record_attempts

    refs = _refs(tmp_path)
    (refs / ATTEMPTS_FILE).symlink_to(victim)

    record_attempts(refs, ["a"])

    assert victim.read_text() == "# the user's own\n"


def test_update_from_folder_does_not_empty_a_folder_a_link_points_at(tmp_path, sample_pdf):
    """refs/.loose -> ~/Documents, and Update deleted everything in it."""
    import shutil

    from sextant.refs.pipeline import rescan_folder

    documents = tmp_path / "home" / "Documents"
    documents.mkdir(parents=True)
    for name in ("thesis.tex", "grant.docx", "notes.txt"):
        (documents / name).write_text("precious")
    refs = _refs(tmp_path)
    (refs / ".loose").symlink_to(documents)
    shutil.copy(sample_pdf, refs / "loose.pdf")

    rescan_folder(refs, [Resolution(key="k", status="no-pdf", title="Something")])

    assert sorted(p.name for p in documents.iterdir()) == ["grant.docx", "notes.txt",
                                                            "thesis.tex"]
    assert (refs / "loose.pdf").exists()
    assert not [p for p in refs.iterdir() if p.name.startswith(".loose-")]


def test_a_download_does_not_write_through_a_link(tmp_path, victim):
    import httpx

    from sextant.refs.http import HttpFetcher

    downloads = _refs(tmp_path) / ".downloads"
    downloads.mkdir()
    (downloads / "k.pdf").symlink_to(victim)
    fetcher = HttpFetcher(resolve=lambda host, port: [(2, 1, 6, "", ("93.184.216.34", port))])
    fetcher._client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"%PDF-1.7 downloaded")))

    assert fetcher.download("https://repo/p.pdf", downloads / "k.pdf")

    assert victim.read_text() == "# the user's own\n"
    assert (downloads / "k.pdf").read_bytes() == b"%PDF-1.7 downloaded"


def test_a_conversion_does_not_write_through_a_link(tmp_path, victim, monkeypatch):
    from sextant.refs import convert

    inbox = _refs(tmp_path) / "inbox"
    inbox.mkdir()
    source = inbox / "spec.docx"
    source.write_bytes(b"a document")
    (inbox / "spec.pdf").symlink_to(victim)
    monkeypatch.setattr(convert, "converter", lambda: "soffice")

    def soffice(argv, **kwargs):
        if "--outdir" not in argv:          # the probe for a network namespace
            return subprocess.CompletedProcess(argv, 0, "", "")
        outdir = argv[argv.index("--outdir") + 1]
        (convert.Path(outdir) / "spec.pdf").write_bytes(b"%PDF-1.7 converted")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(convert, "_run", soffice)

    made = convert.to_pdf(source, inbox, trusted=True)

    assert victim.read_text() == "# the user's own\n"
    assert made.read_bytes() == b"%PDF-1.7 converted"
