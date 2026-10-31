import pytest

from sextant.models import Rect, Span
from sextant.web.geometry import as_fractions


def test_a_rect_becomes_fractions_of_the_page():
    span = Span(page=1, char_start=0, char_end=1, rects=(Rect(50.0, 100.0, 150.0, 120.0),))

    (box,) = as_fractions(span, page_width=500.0, page_height=1000.0)

    assert box == pytest.approx({"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.02})


def test_every_rect_in_the_span_is_converted():
    span = Span(page=1, char_start=0, char_end=1, rects=(
        Rect(0.0, 0.0, 10.0, 10.0),
        Rect(20.0, 0.0, 30.0, 10.0),
    ))

    assert len(as_fractions(span, 100.0, 100.0)) == 2


def test_fractions_are_clamped_into_the_page():
    """A rect that pokes past the page edge must not produce an overlay that
    escapes its container."""
    span = Span(page=1, char_start=0, char_end=1, rects=(Rect(-5.0, 0.0, 120.0, 50.0),))

    (box,) = as_fractions(span, 100.0, 100.0)

    assert box["left"] == 0.0
    assert box["left"] + box["width"] <= 1.0


def test_a_zero_sized_page_yields_nothing_rather_than_dividing_by_zero():
    span = Span(page=1, char_start=0, char_end=1, rects=(Rect(0.0, 0.0, 1.0, 1.0),))

    assert as_fractions(span, 0.0, 0.0) == []


def test_a_span_with_no_rects_yields_nothing():
    assert as_fractions(Span(page=1, char_start=0, char_end=0, rects=()), 100.0, 100.0) == []
