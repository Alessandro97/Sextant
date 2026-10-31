"""Map a character range on a page to the rectangles that should be highlighted."""

from sextant.models import Page, Rect


def rects_for_range(page: Page, char_start: int, char_end: int) -> tuple[Rect, ...]:
    """Rectangles of every word overlapping [char_start, char_end).

    Half-open interval. A word that overlaps by even one character is
    included, so a highlight never clips a word in half.
    """
    if char_end <= char_start:
        return ()

    return tuple(
        word.rect
        for word in page.words
        if word.start < char_end and word.end > char_start
    )
