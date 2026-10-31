from sextant.audit.models import Quantity
from sextant.audit.screen import excerpt_around, screen, screen_all


def test_finds_a_quantity_adjacent_to_its_unit(make_page):
    pages = [make_page("We measured a peak of 3 Mbit/s on the primary replica.")]
    hit = screen(Quantity("3", "Mbit/s", "3 Mbit/s"), pages)
    assert hit is not None
    assert hit.page == 1


def test_the_span_covers_the_quantity_text(make_page):
    text = "We measured a peak of 3 Mbit/s on the primary replica."
    hit = screen(Quantity("3", "Mbit/s", "3 Mbit/s"), [make_page(text)])
    assert "3 Mbit/s" in text[hit.char_start : hit.char_end]


def test_the_span_carries_highlight_rectangles(make_page):
    hit = screen(Quantity("3", "Mbit/s", "3 Mbit/s"), [make_page("a peak of 3 Mbit/s here")])
    assert len(hit.rects) > 0


def test_a_bare_number_without_the_unit_is_not_a_hit(make_page):
    """The whole point. '3' appears; '3 Mbit/s' does not."""
    pages = [make_page("we ran 3 experiments at high rate")]
    assert screen(Quantity("3", "Mbit/s", "3 Mbit/s"), pages) is None


def test_a_different_value_with_the_same_unit_is_not_a_hit(make_page):
    pages = [make_page("a peak of 120 Mbit/s was observed")]
    assert screen(Quantity("3", "Mbit/s", "3 Mbit/s"), pages) is None


def test_a_unit_variant_still_matches(make_page):
    pages = [make_page("a peak of 3 Mbps was observed")]
    assert screen(Quantity("3", "Mbit/s", "3 Mbit/s"), pages) is not None


def test_matching_is_case_insensitive(make_page):
    pages = [make_page("a peak of 3 MBIT/S")]
    assert screen(Quantity("3", "Mbit/s", "3 Mbit/s"), pages) is not None


def test_db_does_not_match_dbm(make_page):
    pages = [make_page("an optical output of 23 dBm")]
    assert screen(Quantity("23", "dB", "23 dB"), pages) is None


def test_searches_every_page_and_reports_the_right_one(make_page):
    pages = [make_page("nothing here", 1), make_page("the clock is 5 GHz here", 2)]
    assert screen(Quantity("5", "GHz", "5 GHz"), pages).page == 2


def test_a_value_of_120_is_not_matched_by_20(make_page):
    """Substring matching on digits would make 20 match inside 120."""
    pages = [make_page("a peak of 120 GHz")]
    assert screen(Quantity("20", "GHz", "20 GHz"), pages) is None


def test_excerpt_gives_the_surrounding_words_for_judgement():
    text = "In the field trial the observed transfer rate was 3 Mbit/s per node overall."
    at = text.index("3 Mbit/s")
    got = excerpt_around(text, at, at + 8, width=30)
    assert "3 Mbit/s" in got
    assert "transfer" in got


def test_excerpt_does_not_run_past_the_text():
    assert excerpt_around("3 GHz", 0, 5, width=99) == "3 GHz"


def test_a_reciprocal_unit_written_iso_style_is_found(make_page):
    """The real case: a cited standard renders the table cell as "1.1 dB K-1"."""
    pages = [make_page("Sensor drift 19 dB K-1 1.1 dB K-1 1.1 dB K-1 max Drift")]

    assert screen(Quantity("1.1", "dB/K", "1.1 dB/K"), pages) is not None


def test_the_reciprocal_form_still_respects_the_value(make_page):
    pages = [make_page("Sensor drift 19 dB K-1 shown in the table")]

    assert screen(Quantity("1.1", "dB/K", "1.1 dB/K"), pages) is None


def test_screen_all_finds_every_occurrence_not_just_the_first(make_page):
    pages = [make_page("peak 3 Mbit/s here", 1),
             make_page("again 3 Mbit/s and 3 Mbit/s", 2)]

    spans, total = screen_all(Quantity("3", "Mbit/s", "3 Mbit/s"), pages)

    assert total == 3
    assert [s.page for s in spans] == [1, 2, 2]


def test_screen_all_reports_the_true_total_when_capped(make_page):
    pages = [make_page(" ".join(["5 GHz"] * 40))]

    spans, total = screen_all(Quantity("5", "GHz", "5 GHz"), pages, limit=6)

    assert len(spans) == 6, "capped for display"
    assert total == 40, "but the reader is told how many there really are"


def test_screen_all_is_as_strict_as_screen(make_page):
    """It must not become a looser matcher just because it returns more."""
    pages = [make_page("we ran 3 experiments and saw 120 Mbit/s")]

    spans, total = screen_all(Quantity("3", "Mbit/s", "3 Mbit/s"), pages)

    assert spans == [] and total == 0


def test_screen_all_returns_nothing_when_absent(make_page):
    spans, total = screen_all(Quantity("99", "GHz", "99 GHz"), [make_page("nothing")])

    assert spans == [] and total == 0


def _q(value, unit):
    return Quantity(value, unit, f"{value} {unit}")


def test_a_trailing_zero_is_the_same_value(make_page):
    """Not finding 2 GHz in a paper that says 2.0 GHz accuses a correct
    citation, which is the worst thing this can do."""
    assert screen(_q("2", "GHz"), [make_page("operating at 2.0 GHz in the test rig")])
    assert screen(_q("0.5", "ms"), [make_page("a latency of 0.50 ms end to end")])


def test_a_trailing_zero_does_not_admit_a_different_value(make_page):
    for text in ("at 2.5 GHz", "at 12 GHz", "at 20 GHz", "at 0.2 GHz", "at 2.05 GHz"):
        assert screen(_q("2", "GHz"), [make_page(text)]) is None, text
    assert screen(_q("0.5", "ms"), [make_page("a latency of 0.55 ms")]) is None


def test_thousands_are_found_however_the_paper_groups_them(make_page):
    for text in ("a 1000 km pipeline", "a 1,000 km pipeline", "a 1 000 km pipeline",
                 "a 1 000 km pipeline"):
        assert screen(_q("1,000", "km"), [make_page(text)]), text
    assert screen(_q("1000", "km"), [make_page("a 1,000 km pipeline")])


def test_thousands_do_not_admit_a_different_value(make_page):
    for text in ("a 2,000 km pipeline", "a 21,000 km pipeline", "a 1,000.5 km pipeline"):
        assert screen(_q("1,000", "km"), [make_page(text)]) is None, text


def test_a_figure_in_a_list_written_without_spaces_is_found(make_page):
    """"5,10,20 ms" is a list, and 20 ms is in it. Refusing a value just after
    a comma turned it into a not-found: an accusation against a correct
    citation, to avoid a wrong pointer at "3,20" written for 3.20."""
    assert screen(_q("20", "ms"), [make_page("delays of 5,10,20 ms across the trial")])


def test_a_trailing_zero_in_the_claim_is_the_same_value(make_page):
    assert screen(_q("2.50", "GHz"), [make_page("operating at 2.5 GHz")])


def test_a_leading_zero_in_the_claim_is_the_same_value(make_page):
    assert screen(_q("05", "dB"), [make_page("a noise reduction of 5 dB")])


def test_the_span_starts_at_the_first_digit(make_page):
    text = "a 100 ms delay"
    hit = screen(_q("100", "ms"), [make_page(text)])
    assert text[hit.char_start:hit.char_end] == "100 ms"
