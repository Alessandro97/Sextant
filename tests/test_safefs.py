"""Writing inside a folder someone else made.

A manuscript folder arrives as a clone, a zip or a tarball, and all three keep
symbolic links. Every test here is one a shipped link would otherwise win.
"""

import pytest

from sextant.safefs import UnsafePathError, real_dir, write_file


def _victim(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bashrc = home / ".bashrc"
    bashrc.write_text("# the user's own\n")
    return bashrc


def test_a_link_where_the_file_goes_is_replaced_not_written_through(tmp_path):
    bashrc = _victim(tmp_path)
    refs = tmp_path / "project" / "refs"
    refs.mkdir(parents=True)
    (refs / "MISSING.md").symlink_to(bashrc)

    write_file(refs / "MISSING.md", "# Missing references\n")

    assert bashrc.read_text() == "# the user's own\n"
    assert not (refs / "MISSING.md").is_symlink()
    assert (refs / "MISSING.md").read_text() == "# Missing references\n"


def test_bytes_are_written_the_same_way(tmp_path):
    bashrc = _victim(tmp_path)
    (tmp_path / "x.pdf").symlink_to(bashrc)

    write_file(tmp_path / "x.pdf", b"%PDF-1.7")

    assert bashrc.read_text() == "# the user's own\n"
    assert (tmp_path / "x.pdf").read_bytes() == b"%PDF-1.7"


def test_nothing_is_written_into_a_folder_that_is_a_link(tmp_path):
    victim = tmp_path / "home" / ".bashrc.d"
    victim.mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    (project / "refs").symlink_to(victim)

    with pytest.raises(UnsafePathError):
        write_file(project / "refs" / "MISSING.md", "payload")

    assert list(victim.iterdir()) == []


def test_a_folder_that_is_a_link_is_refused(tmp_path):
    victim = tmp_path / "elsewhere"
    victim.mkdir()
    (tmp_path / "refs").symlink_to(victim)

    with pytest.raises(UnsafePathError):
        real_dir(tmp_path / "refs")


def test_a_missing_folder_is_made(tmp_path):
    assert real_dir(tmp_path / "refs" / "inbox").is_dir()


def test_a_failed_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    import os

    def refuse(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError):
        write_file(tmp_path / "MISSING.md", "x")

    assert list(tmp_path.iterdir()) == []


def test_a_written_file_gets_the_permissions_an_ordinary_write_would(tmp_path):
    """A temporary file is private, and renaming it into place kept it so: a
    refs/ folder shared with co-authors had reports only one of them could
    read."""
    import stat

    (tmp_path / "ordinary.md").write_text("x")
    write_file(tmp_path / "MISSING.md", "x")

    def mode(name):
        return stat.S_IMODE((tmp_path / name).stat().st_mode)

    assert mode("MISSING.md") == mode("ordinary.md")
