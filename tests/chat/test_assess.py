import pytest

from sextant.chat.assess import assess, build_prompt, parse
from sextant.chat.retrieve import Excerpt

EXCERPTS = [
    Excerpt(page=1, text="Restored wetlands host endangered species.", score=0.4),
    Excerpt(page=7, text="Peat bogs are a key carbon store.", score=0.3),
]
CLAIM = "restored wetlands shelter rare species"


def test_the_prompt_carries_the_claim_and_every_excerpt_with_its_page():
    prompt = build_prompt(CLAIM, EXCERPTS)

    assert CLAIM in prompt
    assert "p. 1" in prompt and "p. 7" in prompt
    assert "endangered" in prompt


def test_the_prompt_offers_all_three_verdicts():
    prompt = build_prompt(CLAIM, EXCERPTS)

    for verdict in ("supports", "related", "unrelated"):
        assert verdict in prompt


def test_parses_a_well_formed_reply():
    verdict, why, _ = parse("VERDICT: supports\nWHY: page 1 says exactly this (p. 1)")

    assert verdict == "supports"
    assert "p. 1" in why


def test_parsing_is_case_insensitive():
    assert parse("verdict: Unrelated\nwhy: different field")[0] == "unrelated"


def test_an_unparseable_reply_becomes_unclear_not_a_guess():
    """Showing the wrong verdict is worse than showing none."""
    verdict, why, _ = parse("I'm not sure what you're asking.")

    assert verdict == "unclear"
    assert "not sure" in why


def test_an_invented_verdict_word_is_rejected():
    assert parse("VERDICT: definitely\nWHY: yes")[0] == "unclear"


def test_assess_returns_the_model_verdict():
    result = assess(CLAIM, EXCERPTS, ask=lambda p: "VERDICT: supports\nWHY: p. 1")

    assert result["verdict"] == "supports"
    assert len(result["excerpts"]) == 2


def test_assess_with_no_excerpts_does_not_call_the_model():
    called = []
    result = assess(CLAIM, [], ask=lambda p: called.append(p) or "VERDICT: supports")

    assert called == []
    assert result["verdict"] == "unclear"


def test_assess_with_an_empty_claim_does_not_call_the_model():
    called = []
    result = assess("  ", EXCERPTS, ask=lambda p: called.append(p) or "x")

    assert called == []
    assert result["verdict"] == "unclear"


def test_a_backend_failure_is_reported_not_raised():
    def boom(prompt):
        raise RuntimeError("not logged in")

    result = assess(CLAIM, EXCERPTS, ask=boom)

    assert result["verdict"] == "unclear"
    assert "not logged in" in result["why"]
    assert len(result["excerpts"]) == 2, "retrieval survives a model failure"


def test_the_reasoning_stops_before_the_quote_lines():
    """DOTALL made WHY swallow everything after it, so a real answer ended
    with the literal text "QUOTE: NONE"."""
    _, why, _ = parse("VERDICT: related\nWHY: on topic (p. 7)\nQUOTE: NONE")

    assert why == "on topic (p. 7)"


def test_a_multi_line_reason_is_still_kept_whole():
    _, why, _ = parse("VERDICT: supports\nWHY: first part\nand its continuation\n"
                   "QUOTE: <p. 2> Something verbatim.")

    assert "first part" in why and "continuation" in why
    assert "QUOTE" not in why


def test_the_prompt_names_the_manuscript_and_the_citation():
    """Without them the model was judging a bare sentence against some
    passages, with no idea what was citing what."""
    prompt = build_prompt("a claim", EXCERPTS, title="Sensor Arrays at Scale",
                          marker="[12]")

    assert "Sensor Arrays at Scale" in prompt
    assert "[12]" in prompt


def test_the_prompt_warns_that_excerpts_may_be_noise():
    """They come from keyword overlap, which is measurably undiscriminating."""
    assert "irrelevant" in build_prompt("c", EXCERPTS).lower()


def test_the_prompt_asks_what_the_verdict_rests_on():
    assert "QUOTE:" in build_prompt("c", EXCERPTS)
    assert "VERBATIM" in build_prompt("c", EXCERPTS)


def test_the_prompt_lets_the_model_blame_the_excerpts_not_the_paper():
    """"Under the baseline conditions" retrieved a standard's boilerplate and
    earned the cited standard an "unrelated" it did not deserve. Judging a paper you
    were shown the wrong pages of is worse than admitting you cannot tell."""
    prompt = build_prompt("c", EXCERPTS)

    assert "unclear" in prompt
    assert "retrieval looks to have failed" in prompt


def test_unclear_is_an_accepted_verdict():
    assert parse("VERDICT: unclear\nWHY: front matter only")[0] == "unclear"


def test_a_score_is_parsed_alongside_the_verdict():
    verdict, why, score = parse("VERDICT: supports\nSCORE: 4\nWHY: it says so (p. 2)")

    assert (verdict, score) == ("supports", 4)
    assert why == "it says so (p. 2)"


def test_a_score_outside_the_scale_is_dropped():
    """-1 is what the prompt asks for when no score is meaningful, and zero
    means "remove this citation" -- not a thing to say by accident."""
    assert parse("VERDICT: unclear\nSCORE: -1\nWHY: wrong pages")[2] is None
    assert parse("VERDICT: supports\nSCORE: 9\nWHY: x")[2] is None


def test_a_missing_score_is_none_not_zero():
    assert parse("VERDICT: related\nWHY: no score line at all")[2] is None


def test_the_prompt_states_what_each_score_means():
    prompt = build_prompt("c", EXCERPTS)

    assert "SCORE:" in prompt
    assert "remove or replace" in prompt, "0 needs a meaning"
    assert "ideal citation" in prompt, "5 needs a meaning"


def test_the_authors_argument_is_weighed_not_obeyed():
    """They know the field and they also want the citation to stand."""
    prompt = build_prompt("c", EXCERPTS, rebuttal="This is the standard source.")

    assert "THE AUTHOR ARGUES" in prompt
    assert "standard source" in prompt
    assert "judge it against the excerpts, not instead of them" in prompt
    assert "agreeing to be agreeable helps nobody" in prompt


def test_no_argument_leaves_the_prompt_unchanged():
    assert "THE AUTHOR ARGUES" not in build_prompt("c", EXCERPTS)


def test_an_unreachable_model_is_marked_retryable():
    """A blip on the way to asking is not an answer about the citation, and
    caching it as one left "could not reach Claude" stuck to a citation for
    the life of the workspace."""
    def broken(_prompt: str) -> str:
        raise RuntimeError("usage limit reached")

    result = assess("a claim", [Excerpt(page=1, text="something", score=0.5)], broken)

    assert result["failed"] is True
    assert "usage limit reached" in result["why"]


def test_a_real_verdict_is_not_marked_retryable():
    result = assess(
        "a claim",
        [Excerpt(page=1, text="something", score=0.5)],
        lambda _p: "VERDICT: related\nSCORE: 3\nWHY: because",
    )

    assert not result.get("failed")


def test_nothing_retrieved_is_settled_not_retryable():
    """No passage matched is a fact about the pair, not a failure to ask."""
    result = assess("a claim", [], lambda _p: "unused")

    assert not result.get("failed")


def _pages(*texts):
    from sextant.models import Page
    return [Page(number=i, text=t, words=()) for i, t in enumerate(texts, 1)]


def test_the_whole_paper_reaches_the_model_when_it_fits():
    """Retrieval choosing what the model may see meant a citation could be
    reported unsupported because the sentence carrying it lost a keyword
    race. Claude can find the correspondence; it needs the paper."""
    from sextant.chat.assess import assess
    from sextant.chat.retrieve import Excerpt

    pages = _pages("Abstract. Throughput reaches around 3 Mbps per node.",
                   "Methodology. A commercial disk array was used.",
                   "Noise floor. The median noise level is about 0 dB.")
    evidence = [Excerpt(page=p.number, text=p.text, score=1.0) for p in pages]
    seen = {}

    def ask(prompt):
        seen["prompt"] = prompt
        return "VERDICT: supports\nSCORE: 4\nWHY: stated\nQUOTE: NONE"

    assess("about 3 Mbit/s per node", evidence, ask=ask, whole_paper=True)

    assert "IN FULL" in seen["prompt"]
    assert "keyword overlap" not in seen["prompt"], "it is not excerpts any more"
    assert "3 Mbps per node" in seen["prompt"], "the abstract reached the model"
    assert all(f"[p. {n}]" in seen["prompt"] for n in (1, 2, 3))


def test_the_reader_is_shown_the_ranked_passages_not_the_whole_paper():
    """Forty pages is not a place to look."""
    from sextant.chat.assess import assess
    from sextant.chat.retrieve import Excerpt

    everything = [Excerpt(page=n, text=f"page {n} body text", score=1.0)
                  for n in range(1, 9)]
    ranked = [Excerpt(page=3, text="page 3 body text", score=0.9)]

    result = assess("a claim", everything, ask=lambda p: "VERDICT: related\nSCORE: 2\n"
                    "WHY: x\nQUOTE: NONE", shown=ranked, whole_paper=True)

    assert [row["page"] for row in result["excerpts"]] == [3]


def test_a_specification_still_goes_through_retrieval():
    """A 375-page document is a quarter of a million tokens per citation."""
    from sextant.web.app import WHOLE_PAPER_CHARS

    assert WHOLE_PAPER_CHARS < 400_000, "must exclude a full standards specification"
    assert WHOLE_PAPER_CHARS > 100_000, "must include an ordinary paper"
