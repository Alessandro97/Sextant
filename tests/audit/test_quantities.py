from sextant.audit.quantities import quantities, unit_variants


def test_extracts_a_value_and_its_unit():
    (q,) = quantities("a rate of 3 Mbit/s per node")
    assert (q.value, q.unit) == ("3", "Mbit/s")


def test_extracts_several_quantities_from_one_claim():
    found = quantities("a peak of 3 Mbit/s with each 5 MHz sampling clock")
    assert [(q.value, q.unit) for q in found] == [("3", "Mbit/s"), ("5", "MHz")]


def test_handles_decimals():
    (q,) = quantities("a 0.5 dB loudness change")
    assert q.value == "0.5"


def test_a_bare_number_with_no_unit_is_not_checkable():
    assert quantities("about 15 patients in the ward") == []


def test_a_year_is_not_a_quantity():
    assert quantities("since 2019 the field has grown") == []


def test_percent_is_a_unit():
    (q,) = quantities("a 20% improvement")
    assert (q.value, q.unit) == ("20", "%")


def test_unit_variants_cover_the_common_spellings():
    assert "mbps" in unit_variants("Mbit/s")
    assert "mb/s" in unit_variants("Mbit/s")


def test_unit_variants_are_lowercase_and_include_the_original():
    assert "ghz" in unit_variants("GHz")


def test_db_variants_do_not_swallow_dbm():
    """dB and dBm are different units. Matching 'dB' must not accept 'dBm'."""
    assert "dbm" not in unit_variants("dB")


def test_figure_of_merit_matches_iso_reciprocal_notation():
    """A cited standard writes "1.1 dB K-1"; the manuscript citing it writes
    "1.1 dB/K". Without this Sextant called a correct citation unsupported."""
    variants = unit_variants("dB/K")

    assert "db/k" in variants
    assert "db k-1" in variants


def test_db_per_k_variants_do_not_leak_into_plain_db():
    assert "db k-1" not in unit_variants("dB")


def test_a_thousands_separator_is_part_of_the_value():
    """It was read as "000 km", which then matched 2,000 km on the page and
    missed the paper's own 1000 km."""
    assert [(q.value, q.unit) for q in quantities("a span of 1,000 km")] == [("1,000", "km")]


def test_a_decimal_comma_is_not_read_as_a_smaller_number():
    """3,5 GHz is 3.5 GHz in half of Europe. It is not 5 GHz."""
    assert quantities("the 3,5 GHz clock") == []


def test_a_decimal_comma_with_two_digits_is_not_a_grouped_value():
    """3,50 GHz is 3.5 GHz, not 350."""
    assert quantities("the 3,50 GHz clock") == []
