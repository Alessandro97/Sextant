"""Repairing text sliced out of a PDF page."""

from sextant.chat.tidy import tidy, tidy_slice, word_bounds


def test_a_word_split_across_a_line_break_is_rejoined():
    assert tidy("rare, en- dangered species") == "rare, endangered species"


def test_real_words_are_never_thrown_away():
    """An earlier attempt judged whether the first token 'looked like a word'
    and deleted 'rare,' and 'species'. That judgement is not possible."""
    assert tidy("rare, endangered species") == "rare, endangered species"


def test_an_email_address_is_dropped():
    got = tidy("Email: {smith, jones}@example.edu). Wetlands store a lot.")

    assert "@" not in got and "Wetlands store" in got


def test_a_url_is_dropped():
    assert "http" not in tidy("See https://example.com/paper for details.")


def test_a_slice_starting_mid_word_is_moved_forward():
    """"emerging" cut at offset 2 must not be sent as "rging"."""
    text = "It is emerging as a key enabler"
    assert tidy_slice(text, text.index("emerging") + 2, len(text)) == "as a key enabler"


def test_a_slice_starting_at_a_word_is_left_alone():
    text = "wetlands store carbon"
    assert tidy_slice(text, 0, len(text)) == text


def test_a_slice_starting_after_a_space_is_left_alone():
    text = "the rain pattern varies"
    assert tidy_slice(text, 4, len(text)) == "rain pattern varies"


def test_a_slice_ending_mid_word_is_pulled_back():
    text = "the crop yield varies following the law"
    assert tidy_slice(text, 0, text.index("following") + 4) == "the crop yield varies"


def test_a_slice_ending_at_a_boundary_keeps_its_last_word():
    text = "the yield varies with rainfall"
    assert tidy_slice(text, 0, len(text)) == text


def test_bounds_never_invert():
    assert word_bounds("abcdefgh", 6, 2)[0] <= word_bounds("abcdefgh", 6, 2)[1]


def test_an_empty_slice_is_survivable():
    assert tidy_slice("", 0, 0) == ""
