"""Searching a document."""

from sextant.index.find import find_all
from sextant.models import Page, Rect, Word


def _page(text: str, number: int = 1) -> Page:
    words, cursor = [], 0
    for token in text.split(" "):
        if token:
            words.append(Word(start=cursor, end=cursor + len(token),
                              rect=Rect(float(cursor), float(number),
                                        float(cursor + len(token)),
                                        float(number) + 1.0)))
        cursor += len(token) + 1
    return Page(number=number, text=text, words=tuple(words))


PAGES = [
    _page("The replica budget assumes a 5 MHz sampling clock.", 1),
    _page("Replica throughput is shared across the main replica.", 2),
]


def test_finds_every_occurrence_with_its_page():
    hits, total = find_all(PAGES, "replica")

    assert total == 3
    assert [h.span.page for h in hits] == [1, 2, 2]


def test_matching_ignores_case():
    assert find_all(PAGES, "REPLICA")[1] == 3


def test_each_hit_carries_rectangles_to_paint():
    hits, _ = find_all(PAGES, "replica")

    assert all(h.span.rects for h in hits)


def test_each_hit_carries_its_surroundings():
    hits, _ = find_all(PAGES, "5 MHz")

    assert "clock" in hits[0].text


def test_a_phrase_spanning_words_is_found():
    hits, total = find_all(PAGES, "replica budget")

    assert total == 1 and hits[0].span.page == 1


def test_a_word_split_across_a_line_break_is_still_found():
    """Page text keeps the hyphen a line break inserted."""
    pages = [_page("protecting rare, en- dangered species")]

    assert find_all(pages, "endangered")[1] == 1


def test_an_empty_query_finds_nothing():
    assert find_all(PAGES, "   ") == ([], 0)


def test_a_missing_word_finds_nothing():
    assert find_all(PAGES, "zebra") == ([], 0)


def test_the_total_is_honest_when_the_list_is_capped():
    pages = [_page(" ".join(["shard"] * 50))]

    hits, total = find_all(pages, "shard", limit=10)

    assert len(hits) == 10 and total == 50
