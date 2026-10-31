from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry
from sextant.refs.resolvers.threegpp import ThreeGppResolver, spec_number


def test_extracts_a_spec_number_from_a_title():
    assert spec_number("Vocabulary for 3GPP Specifications (TR 21.905)") == ("TR", "21.905")
    assert spec_number("3GPP TS 23.501 System architecture for the 5G System") == ("TS", "23.501")


def test_extracts_from_a_number_written_without_a_dot():
    assert spec_number("3GPP TR 21905") == ("TR", "21.905")


def test_returns_none_for_an_ordinary_paper():
    assert spec_number("Adaptive Compression for Distributed Storage Systems") is None


def test_contributes_a_portal_landing_page(tmp_path):
    entry = BibEntry(key="3gpp_tr_21905", entry_type="techreport",
                     title="Vocabulary for 3GPP Specifications (TR 21.905)")

    result = ThreeGppResolver().resolve(entry, FakeFetcher(), tmp_path)

    assert result.status == "no-pdf"
    assert any("21.905" in page for page in result.landing_pages)
    assert result.pdf_path is None


def test_never_claims_to_have_downloaded_anything(tmp_path):
    """ETSI 403s automated requests; pretending otherwise would record a
    resolution with no file."""
    entry = BibEntry(key="k", entry_type="techreport", title="3GPP TS 36.211")

    assert ThreeGppResolver().resolve(entry, FakeFetcher(), tmp_path).pdf_path is None


def test_a_non_standards_entry_is_passed_over(tmp_path):
    entry = BibEntry(key="k", entry_type="article", title="A Normal Paper")

    assert ThreeGppResolver().resolve(entry, FakeFetcher(), tmp_path).status == "unresolved"


def test_falls_back_to_the_citation_key_when_the_title_has_no_number(tmp_path):
    """A key like 3gpp_tr_21905 names the spec when the title does not."""
    entry = BibEntry(key="3gpp_tr_21905", entry_type="techreport",
                     title="Vocabulary for 3GPP Specifications")

    result = ThreeGppResolver().resolve(entry, FakeFetcher(), tmp_path)
    assert result.status == "no-pdf"
