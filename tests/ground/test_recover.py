from sextant.index.extract import extract_pages
from sextant.ground.recover import recover_span


def test_recovers_exact_phrase(sample_pdf):
    pages = extract_pages(sample_pdf)
    span = recover_span(pages, 1, 1, "aggregate write throughput")

    assert span is not None
    assert span.page == 1
    assert pages[0].text[span.char_start : span.char_end] == "aggregate write throughput"
    assert len(span.rects) == 3


def test_recovery_is_case_and_whitespace_insensitive(sample_pdf):
    pages = extract_pages(sample_pdf)
    span = recover_span(pages, 1, 1, "AGGREGATE   WRITE\n throughput")

    assert span is not None
    assert pages[0].text[span.char_start : span.char_end] == "aggregate write throughput"


def test_searches_only_within_the_reported_page_range(sample_pdf):
    pages = extract_pages(sample_pdf)
    # "Cold caches" is on page 2; restricting to page 1 must find nothing.
    assert recover_span(pages, 1, 1, "Cold caches at") is None
    assert recover_span(pages, 2, 2, "Cold caches at") is not None


def test_inclusive_page_range_spanning_both_pages(sample_pdf):
    """A range of 1..2 must find text that lives on page 2.

    The API's end_page_number may be inclusive or exclusive depending on
    version; searching the range inclusively is correct under both readings.
    """
    pages = extract_pages(sample_pdf)
    span = recover_span(pages, 1, 2, "Cold caches at")
    assert span is not None
    assert span.page == 2


def test_returns_none_for_text_not_in_the_document(sample_pdf):
    pages = extract_pages(sample_pdf)
    assert recover_span(pages, 1, 2, "quantum entanglement of volcanic glass") is None


def test_returns_none_for_empty_cited_text(sample_pdf):
    pages = extract_pages(sample_pdf)
    assert recover_span(pages, 1, 2, "   ") is None


def test_recovers_despite_a_dropped_character(sample_pdf):
    pages = extract_pages(sample_pdf)
    # "aggregat" — one character short of the real text
    span = recover_span(pages, 1, 1, "the achievable aggregat write throughput")

    assert span is not None
    assert "aggregate write throughput" in pages[0].text[span.char_start : span.char_end]


def test_low_similarity_is_rejected_rather_than_forced(sample_pdf):
    pages = extract_pages(sample_pdf)
    # Shares only common short words with the page; must not be accepted.
    assert recover_span(pages, 1, 1, "the of and is which a in for to") is None


def test_threshold_is_tunable(sample_pdf):
    pages = extract_pages(sample_pdf)
    garbled = "the achievabl aggregat wrte throughpt"
    assert recover_span(pages, 1, 1, garbled, threshold=0.99) is None
    assert recover_span(pages, 1, 1, garbled, threshold=0.5) is not None


def _highlighted(pages, span):
    return " ".join(pages[span.page - 1].text[span.char_start:span.char_end].split())


def test_a_fuzzy_match_highlights_only_what_it_matched(sample_pdf):
    """The window searched is padded on both sides, and returning the window
    painted a few characters either side of the passage that nothing had
    matched -- a highlight that was not confirmed."""
    pages = extract_pages(sample_pdf)
    span = recover_span(pages, 1, 1, "the achievable aggregat write throughput")

    assert _highlighted(pages, span) == "the achievable aggregate write throughput"


def test_noise_at_either_end_of_the_quote_is_not_highlighted(sample_pdf):
    pages = extract_pages(sample_pdf)
    span = recover_span(pages, 1, 1, "qzx the achievable aggregat write throughput zqx")

    assert span is not None
    assert _highlighted(pages, span) == "the achievable aggregate write throughput"


def test_a_stray_letter_before_the_quote_does_not_widen_the_highlight(sample_pdf):
    pages = extract_pages(sample_pdf)
    span = recover_span(pages, 1, 1, "e the achievable aggregat write throughput")
    assert _highlighted(pages, span) == "the achievable aggregate write throughput"


def test_a_three_letter_match_at_the_end_is_kept(sample_pdf):
    pages = extract_pages(sample_pdf)
    span = recover_span(pages, 1, 1, "the achievable aggregate write throughxxput")
    assert _highlighted(pages, span) == "the achievable aggregate write throughput"
