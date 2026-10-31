from sextant.refs.latex import cited_keys, cited_keys_from_file

SAMPLE = r"""
\documentclass{IEEEtran}
Plots below $3$~m~\cite{Doe24Survey} are common.
Active research~\cite{chen2020first,Okafor22Second, Novak23Third}.
Also \citep{One} and \citet{Two} and \autocite{Three}.
% commented out: \cite{ShouldNotAppear}
\input{sections/method}
"""


def test_extracts_and_deduplicates_keys():
    keys = cited_keys(SAMPLE)
    assert "Doe24Survey" in keys
    assert "One" in keys and "Two" in keys and "Three" in keys


def test_expands_multi_key_citations_and_strips_whitespace():
    keys = cited_keys(SAMPLE)
    assert {"chen2020first", "Okafor22Second", "Novak23Third"} <= keys


def test_ignores_commented_out_citations():
    assert "ShouldNotAppear" not in cited_keys(SAMPLE)


def test_follows_input_and_include(tmp_path):
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "method.tex").write_text(r"Deep in a subfile~\cite{FromInclude}.")
    (tmp_path / "main.tex").write_text(SAMPLE)

    keys = cited_keys_from_file(tmp_path / "main.tex")
    assert "FromInclude" in keys
    assert "Doe24Survey" in keys


def test_missing_input_file_is_ignored_not_fatal(tmp_path):
    (tmp_path / "main.tex").write_text(r"\input{nope}" + "\n" + r"\cite{Still}")
    assert "Still" in cited_keys_from_file(tmp_path / "main.tex")


def test_the_real_manuscript_yields_twenty_five_keys(real_tex_text):
    """The distinct keys counted by hand in the manuscript SEXTANT_TEST_TEX
    names; a different manuscript needs its own count here."""
    assert len(cited_keys(real_tex_text)) == 25
