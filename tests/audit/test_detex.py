from sextant.audit.detex import detex


def test_unwraps_glossary_macros_keeping_the_term():
    assert detex(r"The \gls{pcr} are repeated") == "The pcr are repeated"


def test_strips_inline_math_delimiters_but_keeps_the_number():
    assert detex(r"below $3$~GHz") == "below 3 GHz"


def test_drops_labels_and_refs_entirely():
    assert detex(r"as shown in Fig.~\ref{fig:one} the rate") == "as shown in Fig. the rate"


def test_drops_cite_commands():
    assert detex(r"a rate of 3 Mbit/s~\cite{Doe25}") == "a rate of 3 Mbit/s"


def test_keeps_subscripted_symbols_readable():
    assert detex(r"L_{\text{CPU}}=23~ms") == "L_ CPU =23 ms"


def test_unknown_macros_become_whitespace_not_glue():
    """\\textbf{fast} must not become 'textbffast'."""
    assert detex(r"is \textbf{very} fast") == "is very fast"


def test_collapses_runs_of_whitespace():
    assert detex("a   \n  b") == "a b"


def test_a_percent_sign_survives_because_it_is_a_unit():
    assert detex(r"a 20\% gain") == "a 20% gain"
