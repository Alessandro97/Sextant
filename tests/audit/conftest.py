"""Shared fixtures for audit tests."""

import pytest

from sextant.models import Page, Rect, Word


def page_from(text: str, number: int = 1) -> Page:
    """Build a Page whose words tile `text` exactly, as extract_pages does.

    Rectangles are synthetic but ordered, which is all the screen tests need:
    they assert on spans and page numbers, not geometry.
    """
    words: list[Word] = []
    cursor = 0
    for token in text.split(" "):
        if token:
            words.append(
                Word(
                    start=cursor,
                    end=cursor + len(token),
                    rect=Rect(
                        float(cursor),
                        float(number),
                        float(cursor + len(token)),
                        float(number) + 1.0,
                    ),
                )
            )
        cursor += len(token) + 1
    return Page(number=number, text=text, words=tuple(words))


@pytest.fixture
def make_page():
    """Factory fixture, so tests need no cross-module import."""
    return page_from
