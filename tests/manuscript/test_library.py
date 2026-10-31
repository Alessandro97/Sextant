import pytest

from sextant.manuscript.library import (
    POINTER,
    default_refs_for,
    refs_for,
    set_refs_for,
)


@pytest.fixture
def registry(tmp_path):
    """Where Sextant keeps the choices: beside its own data, not the paper."""
    return tmp_path / "data" / "libraries.json"


@pytest.fixture
def manuscript(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    path = folder / "paper.pdf"
    path.write_bytes(b"%PDF")
    return path


def test_the_library_defaults_to_refs_beside_the_manuscript(manuscript, registry):
    assert refs_for(manuscript, registry) == manuscript.parent / "refs"


def test_a_chosen_folder_is_remembered(manuscript, registry, tmp_path):
    elsewhere = tmp_path / "my-papers"
    elsewhere.mkdir()

    set_refs_for(manuscript, elsewhere, registry)

    assert refs_for(manuscript, registry) == elsewhere.resolve()


def test_the_choice_is_kept_with_sextants_data_not_beside_the_manuscript(
        manuscript, registry, tmp_path):
    """A pointer beside the manuscript is one a folder someone sent can ship."""
    set_refs_for(manuscript, tmp_path / "elsewhere", registry)

    assert registry.is_file()
    assert not (manuscript.parent / POINTER).exists()


def test_asking_never_creates_the_folder(manuscript, registry):
    """Silently making directories in someone's project is how a file ends up
    somewhere they will not think to look."""
    assert not refs_for(manuscript, registry).exists()


@pytest.mark.parametrize("shipped", ["~/.bashrc.d", "/etc/profile.d", "../elsewhere"])
def test_a_shipped_pointer_cannot_send_the_library_out_of_the_folder(
        manuscript, registry, shipped):
    """.sextant-library reading ~/.bashrc.d had the report written where
    Fedora's next shell sources every file."""
    (manuscript.parent / POINTER).write_text(shipped)

    chosen = refs_for(manuscript, registry)

    # No ~ is expanded, so "~/.bashrc.d" is a folder called "~" in the project.
    assert chosen.is_relative_to(manuscript.parent)


def test_a_pointer_to_a_folder_inside_the_manuscripts_own_is_honoured(
        manuscript, registry):
    (manuscript.parent / POINTER).write_text("papers")

    assert refs_for(manuscript, registry) == manuscript.parent / "papers"


def test_a_pointer_cannot_leave_the_folder_through_a_link(manuscript, registry, tmp_path):
    outside = tmp_path / "home" / ".bashrc.d"
    outside.mkdir(parents=True)
    (manuscript.parent / "lib").symlink_to(outside)
    (manuscript.parent / POINTER).write_text("lib")

    assert refs_for(manuscript, registry) == default_refs_for(manuscript)


def test_a_pointer_that_is_itself_a_link_is_ignored(manuscript, registry, tmp_path):
    real = tmp_path / "pointer"
    real.write_text("papers")
    (manuscript.parent / POINTER).symlink_to(real)

    assert refs_for(manuscript, registry) == default_refs_for(manuscript)


def test_a_corrupt_pointer_falls_back_to_the_default(manuscript, registry):
    (manuscript.parent / POINTER).write_text("   ")

    assert refs_for(manuscript, registry) == default_refs_for(manuscript)


def test_a_choice_made_in_sextant_beats_a_pointer(manuscript, registry, tmp_path):
    elsewhere = tmp_path / "my-papers"
    elsewhere.mkdir()
    (manuscript.parent / POINTER).write_text("papers")

    set_refs_for(manuscript, elsewhere, registry)

    assert refs_for(manuscript, registry) == elsewhere.resolve()


def test_an_unreadable_registry_falls_back_to_the_default(manuscript, registry):
    registry.parent.mkdir(parents=True)
    registry.write_text("not json at all")

    assert refs_for(manuscript, registry) == default_refs_for(manuscript)
