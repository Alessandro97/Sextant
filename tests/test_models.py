from sextant.models import Rect, Word, Page, Span


def test_page_words_carry_char_offsets_and_rects():
    words = (
        Word(start=0, end=3, rect=Rect(0.0, 0.0, 10.0, 5.0)),
        Word(start=4, end=9, rect=Rect(11.0, 0.0, 30.0, 5.0)),
    )
    page = Page(number=1, text="the quick", words=words)

    assert page.number == 1
    assert page.text[words[1].start:words[1].end] == "quick"


def test_span_is_hashable_and_frozen():
    span = Span(page=2, char_start=5, char_end=9, rects=(Rect(0.0, 0.0, 1.0, 1.0),))
    assert hash(span)
    assert span.char_end - span.char_start == 4
