import pymupdf
import pytest

from sextant.manuscript.discover import NoCompiledPdfError, compiled_pdf_for


def _pdf_with_links(path, keys=("Smith20",)):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72.0, 100.0), "text [1]", fontsize=11)
    for key in keys:
        page.insert_link({"kind": pymupdf.LINK_NAMED,
                          "from": pymupdf.Rect(100, 90, 110, 102),
                          "name": f"cite.{key}"})
    doc.save(path)
    doc.close()
    return path


def _plain_pdf(path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72.0, 100.0), "nothing", fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_a_pdf_path_is_returned_as_is(tmp_path):
    pdf = _pdf_with_links(tmp_path / "m.pdf")

    assert compiled_pdf_for(pdf) == pdf


def test_a_pdf_path_is_accepted_even_without_citation_links(tmp_path):
    """An explicit PDF is the user's decision; failing later with a clear
    message beats second-guessing the path they typed."""
    plain = _plain_pdf(tmp_path / "plain.pdf")

    assert compiled_pdf_for(plain) == plain


def test_finds_the_compiled_pdf_beside_a_tex_file(tmp_path):
    (tmp_path / "main.tex").write_text(r"\cite{Smith20}")
    pdf = _pdf_with_links(tmp_path / "paper-v2.pdf")

    assert compiled_pdf_for(tmp_path / "main.tex") == pdf


def test_prefers_a_pdf_that_actually_has_citation_links(tmp_path):
    """A manuscript directory usually holds figures too."""
    (tmp_path / "main.tex").write_text(r"\cite{Smith20}")
    _plain_pdf(tmp_path / "figure.pdf")
    real = _pdf_with_links(tmp_path / "output.pdf")

    assert compiled_pdf_for(tmp_path / "main.tex") == real


def test_searches_one_level_of_subdirectory(tmp_path):
    (tmp_path / "main.tex").write_text(r"\cite{Smith20}")
    (tmp_path / "build").mkdir()
    pdf = _pdf_with_links(tmp_path / "build" / "main.pdf")

    assert compiled_pdf_for(tmp_path / "main.tex") == pdf


def test_ignores_the_refs_folder(tmp_path):
    """refs/ holds downloaded papers, which carry citation links of their own."""
    (tmp_path / "main.tex").write_text(r"\cite{Smith20}")
    (tmp_path / "refs").mkdir()
    _pdf_with_links(tmp_path / "refs" / "SomeCitedPaper.pdf")

    with pytest.raises(NoCompiledPdfError):
        compiled_pdf_for(tmp_path / "main.tex")


def test_says_so_clearly_when_there_is_no_compiled_output(tmp_path):
    (tmp_path / "main.tex").write_text(r"\cite{Smith20}")

    with pytest.raises(NoCompiledPdfError) as excinfo:
        compiled_pdf_for(tmp_path / "main.tex")

    assert "compile" in str(excinfo.value).lower()


def test_resolves_the_real_manuscript_from_its_tex(real_tex_text, real_manuscript_pdf):
    """The user types main.tex; the compiled output is what drives the reader."""
    found = compiled_pdf_for(real_manuscript_pdf.parent / "main.tex")

    assert found.suffix == ".pdf"
    from sextant.manuscript.discover import has_citation_links

    assert has_citation_links(found)
