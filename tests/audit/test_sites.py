from sextant.audit.sites import citation_sites, citation_sites_from_file

SAMPLE = r"""
Existing systems are slow. Field trials report only $3$~Mbit/s per
node~\cite{Doe25Trial}. Active research continues~\cite{One,Two}.
% commented out: \cite{ShouldNotAppear}
"""


def test_finds_one_site_per_cite_command():
    sites = citation_sites(SAMPLE, source="main.tex")
    assert len(sites) == 2


def test_the_claim_window_is_the_sentence_before_the_cite():
    sites = citation_sites(SAMPLE, source="main.tex")
    assert "3 Mbit/s per node" in sites[0].claim
    # The previous sentence is a different claim and must not bleed in.
    assert "Existing systems are slow" not in sites[0].claim


def test_a_multi_key_cite_is_one_site_with_both_keys():
    sites = citation_sites(SAMPLE, source="main.tex")
    assert sites[1].keys == ("One", "Two")


def test_commented_out_citations_are_ignored():
    keys = {k for site in citation_sites(SAMPLE, source="m.tex") for k in site.keys}
    assert "ShouldNotAppear" not in keys


def test_an_escaped_percent_does_not_start_a_comment():
    text = r"A 20\% gain~\cite{Key}."
    sites = citation_sites(text, source="m.tex")
    assert sites[0].keys == ("Key",)
    assert "20% gain" in sites[0].claim


def test_records_the_line_number_for_the_report():
    sites = citation_sites(SAMPLE, source="main.tex")
    assert sites[0].line == 3


def test_follows_input_directives(tmp_path):
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "m.tex").write_text(r"Deep claim of 5~GHz~\cite{Sub}.")
    (tmp_path / "main.tex").write_text("Top.\n" + r"\input{sections/m}")

    sites = citation_sites_from_file(tmp_path / "main.tex")
    keys = {k for s in sites for k in s.keys}
    assert "Sub" in keys
    assert any(s.source.endswith("m.tex") for s in sites)


def test_a_missing_input_is_skipped_not_fatal(tmp_path):
    (tmp_path / "main.tex").write_text(r"\input{nope}" + "\n" + r"Rate is 9~GHz~\cite{Still}.")
    keys = {k for s in citation_sites_from_file(tmp_path / "main.tex") for k in s.keys}
    assert "Still" in keys


def test_the_real_manuscript_yields_the_measured_site_count(real_tex_text):
    """Measured on 2026-08-06: 29 \\cite commands across the manuscript."""
    assert len(citation_sites(real_tex_text, source="main.tex")) == 29


def test_the_measured_share_of_sites_carry_a_checkable_quantity(real_tex_text):
    """Measured on 2026-08-06: 8 of 29 sites name a number with a unit.

    This is the number that sets expectations for the tool: roughly a quarter
    of citations are machine-checkable, and the rest are reported for a human
    to judge.
    """
    from sextant.audit.quantities import quantities

    sites = citation_sites(real_tex_text, source="main.tex")
    assert len([s for s in sites if quantities(s.claim)]) == 8


def test_a_claim_starts_after_an_earlier_cite_in_the_same_sentence():
    """b was being checked for a's 20 ms, and faulted when its paper lacked it."""
    sites = citation_sites(
        r"Latency is 20~ms~\cite{a} while capacity is 5~Gbps~\cite{b}.")

    assert "20 ms" in sites[0].claim
    assert "20 ms" not in sites[1].claim
    assert "5 Gbps" in sites[1].claim


def test_back_to_back_cites_are_one_joint_citation():
    """\\cite{a}, \\cite{b} is \\cite{a,b} written twice. The second used to get
    a claim of "," and the first was faulted for the figure the second gave."""
    sites = citation_sites(r"Capacity reaches 5~Gbps~\cite{a}, \cite{b}.")

    assert len(sites) == 1
    assert sites[0].keys == ("a", "b")
    assert "5 Gbps" in sites[0].claim


def test_cites_with_words_between_them_stay_separate():
    sites = citation_sites(r"Latency is 20~ms~\cite{a} and capacity 5~Gbps~\cite{b}.")
    assert [s.keys for s in sites] == [("a",), ("b",)]
