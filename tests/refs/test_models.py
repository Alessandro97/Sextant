from sextant.refs.models import BibEntry, LinkCheck, Resolution


def test_bib_entry_defaults_are_none_not_empty_string():
    entry = BibEntry(key="Smith20", entry_type="article", title="A Paper")
    assert entry.doi is None
    assert entry.year is None


def test_resolution_records_why_it_failed():
    r = Resolution(key="Smith20", status="unresolved", reason="no OA pdf_url")
    assert r.pdf_path is None
    assert "no OA" in r.reason


def test_resolution_carries_landing_pages_for_manual_retrieval():
    r = Resolution(
        key="Smith20",
        status="no-pdf",
        reason="OA flagged but no direct PDF",
        landing_pages=("https://zenodo.org/record/1", "http://hdl.handle.net/2"),
    )
    assert len(r.landing_pages) == 2


def test_link_check_is_hashable_and_frozen():
    lc = LinkCheck(key="Smith20", verdict="match", claimed="A Paper", actual="A Paper")
    assert hash(lc)
