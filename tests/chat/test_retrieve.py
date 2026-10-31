from pathlib import Path

import pytest

from sextant.chat import retrieve
from sextant.chat.retrieve import Excerpt, top_excerpts
from sextant.models import Page, Rect, Word


def _page(text: str, number: int = 1) -> Page:
    words, cursor = [], 0
    for token in text.split(" "):
        if token:
            words.append(Word(start=cursor, end=cursor + len(token),
                              rect=Rect(0.0, float(number), 1.0, float(number) + 1.0)))
        cursor += len(token) + 1
    return Page(number=number, text=text, words=tuple(words))


PAGES = [
    _page("The write path assumes a 5 ms interval and 3 Mbit/s throughput.", 1),
    _page("Garbage collection pauses are traced by the allocator logs.", 2),
    _page("Cold caches and the -31 dB/K setting dominate the tail.", 3),
]


def test_returns_the_passage_that_matches_the_question():
    hits = top_excerpts("what is the write throughput?", PAGES, limit=1)

    assert hits[0].page == 1
    assert "3 Mbit/s" in hits[0].text


def test_ranks_a_better_match_above_a_worse_one():
    hits = top_excerpts("cold caches setting tail", PAGES, limit=2)

    assert hits[0].page == 3


def test_respects_the_limit():
    assert len(top_excerpts("the", PAGES, limit=2)) <= 2


def test_every_excerpt_names_its_page_so_an_answer_can_cite_it():
    for hit in top_excerpts("caches allocator throughput", PAGES, limit=3):
        assert hit.page in (1, 2, 3)


def test_a_question_matching_nothing_returns_nothing_rather_than_noise():
    assert top_excerpts("zzzz qqqq vvvv", PAGES, limit=3) == []


def test_an_empty_question_returns_nothing():
    assert top_excerpts("   ", PAGES, limit=3) == []


def test_stopwords_alone_do_not_match_everything():
    """'what is the' must not retrieve every page in the paper."""
    assert top_excerpts("what is the", PAGES, limit=3) == []


def test_an_excerpt_is_a_contiguous_span_of_the_page():
    (hit,) = top_excerpts("allocator logs", PAGES, limit=1)

    assert isinstance(hit, Excerpt)
    assert hit.text in PAGES[1].text


def test_at_most_one_excerpt_per_page():
    long_page = _page("throughput " * 200, 1)

    hits = top_excerpts("throughput", [long_page], limit=4)

    assert len(hits) == 1


def test_a_question_in_the_past_tense_still_matches_present_tense_prose():
    """Without suffix folding, "what rates were reached" retrieves nothing
    from a paper that says "rates reach"."""
    pages = [_page("Rates reach 3 Mbit/s in the write path.", 1)]

    hits = top_excerpts("what rates were reached?", pages, limit=1)

    assert hits and hits[0].page == 1


def test_folding_does_not_collapse_short_words_into_each_other():
    """'is' -> 'i' and similar would make everything match everything."""
    from sextant.chat.retrieve import _fold

    assert _fold("gas") == "gas"
    assert _fold("reached") == "reach"
    assert _fold("rates") == "rate"


def test_a_word_ending_a_sentence_matches_itself_elsewhere():
    """The token pattern admits "." so that "4.312" survives whole, which
    also glued a full stop onto every sentence-final word."""
    from sextant.chat.retrieve import _terms

    assert _terms("the replica.") & _terms("replica budget")


def test_a_unit_is_not_treated_as_a_plural():
    """"Mbit/s" folded to "mbit/", which matched nothing."""
    from sextant.chat.retrieve import _terms

    assert _terms("3 Mbit/s.") & _terms("peak 3 Mbit/s ingest")
    assert "mbit/s" in _terms("3 Mbit/s")


def test_a_specification_number_survives_intact():
    from sextant.chat.retrieve import _terms

    assert "4.312" in _terms("see clause 4.312 for details")


def _doc(*texts: str) -> list[Page]:
    return [Page(number=i, text=t, words=()) for i, t in enumerate(texts, start=1)]


def test_rare_terms_outrank_common_ones():
    """A page matching only a ubiquitous word must lose to one matching a rare
    word. Unweighted, both scored one term out of the query and tied."""
    pages = _doc(
        *["the system reports a value in ms every cycle"] * 8,
        "reweighting of the batch is performed on the server",
    )
    best = top_excerpts("reweighting takes 5 ms", pages, limit=1)

    assert best and best[0].page == 9


def test_terms_absent_everywhere_do_not_dilute():
    """A passage is scored on what the document could offer, not on the words
    of the claim that appear nowhere in it.

    The 375-page specification never writes "tproc" or "reweighting"; scoring
    against the whole sentence buried its own relevant clause among front
    matter."""
    pages = _doc("lookup and indexing scheme tables", "unrelated front matter")
    hit = top_excerpts(
        "tproc reweighting lookup and indexing scheme", pages, limit=1
    )[0]

    # Every term the document has, so a full share -- not 3/5 for the two it
    # could never have matched.
    assert hit.page == 1
    assert hit.score == pytest.approx(1.0)


def test_score_is_never_used_as_a_support_signal():
    """Pinned as documentation: the score ranks passages inside one document
    and is not comparable across documents. Measured on a real manuscript,
    an unrelated claim scored higher against a random paper (0.475) than a
    correct citation scored against the specification it cites (0.216), so no
    threshold on it can decide whether a citation is supported."""
    source = Path(retrieve.__file__).read_text()

    assert "MIN_RELEVANCE" not in source


def test_the_same_rate_written_two_ways_matches():
    """A manuscript saying "3 Mbit/s" cited a paper whose abstract says "3
    Mbps". Neither the number nor the unit matched, so the one passage that
    answered the citation scored on "shard" and "per" and lost."""
    from sextant.chat.retrieve import _terms

    claim = _terms("about 3 Mbit/s shared per shard")
    abstract = _terms("around 3 Mbps per shard under steady load")

    assert {"3", "mbit/s"} <= claim & abstract


def test_megabytes_are_not_folded_into_megabits():
    """Lowercasing loses the case that separates MB/s from Mb/s, so the
    ambiguous spelling is deliberately left alone."""
    from sextant.chat.retrieve import _terms

    assert _terms("12 MB/s") & _terms("12 Mbit/s") == {"12"}


def test_a_bare_number_survives_tokenising():
    """It is the whole point of a quantity claim; dropping everything under
    two characters threw away the "3" in "3 Mbit/s"."""
    from sextant.chat.retrieve import _terms

    assert "3" in _terms("about 3 Mbit/s")


def test_the_abstract_is_reachable_when_it_carries_the_figure():
    from sextant.chat.retrieve import top_excerpts
    from sextant.models import Page

    pages = [
        Page(number=1, text="Abstract. Throughput reaches around 3 Mbps per shard "
                            "under steady load across the campaign.", words=()),
        Page(number=2, text="Methodology. Measurements were collected with a "
                            "standard client over several weeks of runs.", words=()),
    ]

    best = top_excerpts("the cluster delivers about 3 Mbit/s per shard", pages, limit=2)

    assert best[0].page == 1
