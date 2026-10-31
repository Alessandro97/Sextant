import os

import pytest

from sextant.refs.folder import key_pdf, materialize, refs_dir
from sextant.refs.models import Resolution


def test_creates_a_symlink_named_by_citation_key(tmp_path, sample_pdf):
    out = refs_dir(tmp_path / "main.tex")
    materialize([Resolution(key="Doe24Survey", status="resolved",
                            pdf_path=str(sample_pdf))], out)

    link = out / "Doe24Survey.pdf"
    assert link.is_symlink()
    assert link.resolve() == sample_pdf.resolve()


def test_relinks_cleanly_when_run_twice(tmp_path, sample_pdf):
    out = refs_dir(tmp_path / "main.tex")
    r = [Resolution(key="k", status="resolved", pdf_path=str(sample_pdf))]
    materialize(r, out)
    materialize(r, out)  # must not raise FileExistsError

    assert (out / "k.pdf").is_symlink()


def test_missing_md_lists_unresolved_refs_with_their_landing_pages(tmp_path):
    out = refs_dir(tmp_path / "main.tex")
    materialize([
        Resolution(key="Paywalled", status="no-pdf", reason="no url_for_pdf",
                   doi="10.5555/test.2017.0001", title="Rapid Sediment Transport",
                   landing_pages=("https://zenodo.org/record/1234567",)),
    ], out)

    text = (out / "MISSING.md").read_text()
    assert "Paywalled" in text
    assert "10.5555/test.2017.0001" in text
    assert "https://zenodo.org/record/1234567" in text
    assert "https://doi.org/10.5555/test.2017.0001" in text


def test_resolved_refs_do_not_appear_in_missing_md(tmp_path, sample_pdf):
    out = refs_dir(tmp_path / "main.tex")
    materialize([Resolution(key="Got", status="resolved", pdf_path=str(sample_pdf))], out)

    assert "Got" not in (out / "MISSING.md").read_text()


def test_missing_md_says_so_when_nothing_is_missing(tmp_path, sample_pdf):
    out = refs_dir(tmp_path / "main.tex")
    materialize([Resolution(key="Got", status="resolved", pdf_path=str(sample_pdf))], out)

    assert "Nothing missing" in (out / "MISSING.md").read_text()


def test_inbox_directory_is_created(tmp_path):
    out = refs_dir(tmp_path / "main.tex")
    materialize([], out)
    assert (out / "inbox").is_dir()


def test_a_pdf_already_at_the_link_path_is_not_destroyed(tmp_path):
    """Regression, found only by a live run.

    Resolvers download into a directory the caller chooses. If that is the
    refs folder itself, the link path and the source path are the SAME file:
    unlinking it first destroyed every downloaded PDF and left a symlink
    pointing at itself. Every unit test passed because they used two
    different tmp directories.
    """
    out = tmp_path / "refs"
    out.mkdir()
    real = out / "k.pdf"
    real.write_bytes(b"%PDF-1.7 downloaded")

    materialize([Resolution(key="k", status="resolved", pdf_path=str(real))], out)

    assert (out / "k.pdf").exists(), "the downloaded file was destroyed"
    assert (out / "k.pdf").read_bytes().startswith(b"%PDF")


def test_a_key_cannot_place_its_link_outside_the_refs_folder(tmp_path, sample_pdf):
    """Keys come from the manuscript, and a manuscript can be anyone's.

    A PDF whose hyperref destination reads cite.../../thesis made fetch
    unlink ~/Documents/thesis.pdf and leave a symlink in its place.
    """
    victim = tmp_path / "thesis.pdf"
    victim.write_bytes(b"%PDF-1.7 the only copy")
    out = tmp_path / "manuscript" / "refs"

    materialize([Resolution(key="../../thesis", status="resolved",
                            pdf_path=str(sample_pdf))], out)

    assert not victim.is_symlink()
    assert victim.read_bytes() == b"%PDF-1.7 the only copy"
    assert key_pdf(out, "../../thesis").parent == out


def test_a_key_with_a_slash_gets_a_link_of_its_own(tmp_path, sample_pdf):
    """DBLP keys look like DBLP:journals/corr/abs-2501-00001."""
    key = "DBLP:journals/corr/abs-2501-00001"
    out = refs_dir(tmp_path / "main.tex")

    materialize([Resolution(key=key, status="resolved",
                            pdf_path=str(sample_pdf))], out)

    link = key_pdf(out, key)
    assert link.parent == out
    assert link.is_symlink()
    assert link.resolve() == sample_pdf.resolve()


def test_keys_differing_only_in_unsafe_characters_get_different_files(tmp_path):
    paths = {key_pdf(tmp_path, k) for k in ("a/b", "a:b", "a_b", "a?b")}
    assert len(paths) == 4
    assert {p.parent for p in paths} == {tmp_path}


def test_an_ordinary_key_keeps_its_own_name(tmp_path):
    """Existing refs/ folders are named this way and must keep working."""
    for key in ("Doe24Survey", "who_report_2021", "smith-2020", "li+wang.v2"):
        assert key_pdf(tmp_path, key) == tmp_path / f"{key}.pdf"


def test_a_file_the_user_put_at_the_link_path_is_left_alone(tmp_path, sample_pdf):
    """refs/ is a folder people already keep, annotated copies and all."""
    out = refs_dir(tmp_path / "main.tex")
    out.mkdir(parents=True)
    theirs = out / "smith2020.pdf"
    theirs.write_bytes(b"%PDF-1.7 annotated by hand")

    materialize([Resolution(key="smith2020", status="resolved",
                            pdf_path=str(sample_pdf))], out)

    assert not theirs.is_symlink()
    assert theirs.read_bytes() == b"%PDF-1.7 annotated by hand"


@pytest.mark.skipif(os.name == "nt", reason="a colon is not a filename character there")
@pytest.mark.parametrize("key", ["Smith:2020", "Smith 2020", "smith&jones2020", "o'brien2021"])
def test_a_key_any_filesystem_here_can_name_keeps_its_own_name(tmp_path, key):
    """refs/Smith:2020.pdf already exists in folders made before keys were
    made safe; renaming it hid the paper: verified became no-source."""
    assert key_pdf(tmp_path, key) == tmp_path / f"{key}.pdf"


@pytest.mark.parametrize("key", [".hidden", "../../thesis"])
def test_no_key_becomes_a_hidden_file(tmp_path, key):
    """A dotfile in refs/ is one nobody browsing the folder would see."""
    assert not key_pdf(tmp_path, key).name.startswith(".")


@pytest.mark.skipif(os.name != "nt", reason="only Windows reserves these names")
@pytest.mark.parametrize("key", ["CON", "Nul", "com1", "LPT9"])
def test_a_reserved_windows_name_is_renamed_whatever_its_case(tmp_path, key):
    assert key_pdf(tmp_path, key).stem.lower() != key.lower()


def test_a_dangling_link_is_replaced(tmp_path, sample_pdf):
    """A link to a paper since moved is still a link Sextant made."""
    out = tmp_path / "refs"
    out.mkdir()
    (out / "k.pdf").symlink_to(tmp_path / "moved-away.pdf")

    materialize([Resolution(key="k", status="resolved", pdf_path=str(sample_pdf))], out)

    assert (out / "k.pdf").resolve() == sample_pdf.resolve()
