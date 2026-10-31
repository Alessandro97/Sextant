from sextant.index.extract import extract_pages
from sextant.index.locate import rects_for_range
from sextant.models import Page, Rect, Word

PAGE = Page(
    number=1,
    text="the quick brown fox",
    words=(
        Word(0, 3, Rect(0.0, 0.0, 10.0, 5.0)),
        Word(4, 9, Rect(11.0, 0.0, 30.0, 5.0)),
        Word(10, 15, Rect(31.0, 0.0, 50.0, 5.0)),
        Word(16, 19, Rect(51.0, 0.0, 60.0, 5.0)),
    ),
)


def test_returns_only_overlapping_words():
    rects = rects_for_range(PAGE, 4, 15)
    assert rects == (PAGE.words[1].rect, PAGE.words[2].rect)


def test_partial_overlap_still_includes_the_word():
    rects = rects_for_range(PAGE, 6, 7)
    assert rects == (PAGE.words[1].rect,)


def test_range_landing_entirely_in_a_separator_returns_nothing():
    assert rects_for_range(PAGE, 3, 4) == ()


def test_empty_range_returns_nothing():
    assert rects_for_range(PAGE, 5, 5) == ()


def test_rects_cover_the_expected_words_on_a_real_pdf(sample_pdf):
    page = extract_pages(sample_pdf)[0]
    needle = "aggregate"
    start = page.text.index(needle)
    rects = rects_for_range(page, start, start + len(needle))
    assert len(rects) == 1
