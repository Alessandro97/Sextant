"""Span rectangles -> display-independent fractions of the page.

Verified visually: get_text("words") rects share page-point space with
page.rect and scale linearly under Matrix(z, z). Dividing by the page size
therefore gives numbers the browser can turn into CSS percentages, so the
overlay lands correctly at any display width and zoom costs nothing.
"""

from sextant.models import Rect, Span


def rect_as_fraction(rect: Rect, page_width: float, page_height: float) -> dict:
    """One rect as {left, top, width, height}, all in [0, 1]."""
    left = _clamp(rect.x0 / page_width)
    top = _clamp(rect.y0 / page_height)
    right = _clamp(rect.x1 / page_width)
    bottom = _clamp(rect.y1 / page_height)
    return {
        "left": left,
        "top": top,
        "width": max(0.0, right - left),
        "height": max(0.0, bottom - top),
    }


def as_fractions(span: Span, page_width: float, page_height: float) -> list[dict]:
    """Each rect of a span as page-size fractions."""
    if page_width <= 0 or page_height <= 0:
        return []
    return [rect_as_fraction(rect, page_width, page_height) for rect in span.rects]


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
