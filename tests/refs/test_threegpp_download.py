"""3GPP specifications, downloaded from the 3GPP archive.

The archive lists one zip per version, each holding a Word document. Measured
2026-10-31: the listing is plain HTML and the zips download without a login.
"""

import io
import zipfile

import pymupdf
import pytest

from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry
from sextant.refs.resolvers import threegpp
from sextant.refs.resolvers.threegpp import ThreeGppResolver, archive_url, spec_number

ARCHIVE = "https://www.3gpp.org/ftp/Specs/archive/23_series/23.501/"


def _listing(*versions):
    links = "".join(f'<a href="{ARCHIVE}23501-{v}.zip">23501-{v}.zip</a>\n' for v in versions)
    return f"<html><body>{links}</body></html>"


def _zip(*members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members:
            archive.writestr(name, data)
    return buffer.getvalue()


def _cover(text):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 80), text, fontsize=10)
    return doc.tobytes()


@pytest.fixture
def converts(monkeypatch):
    """Stands in for LibreOffice: the 'converted' PDF shows `cover`."""
    made = {}

    def to_pdf(source, out_dir, trusted=False):
        assert trusted, "a specification from the 3GPP archive is converted as trusted"
        made["source"] = source
        target = out_dir / f"{source.stem}.pdf"
        target.write_bytes(_cover(made.get("cover", "3GPP TS 23.501 V17.3.0 (2021-12)")))
        return target

    monkeypatch.setattr(threegpp, "converter", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(threegpp, "to_pdf", to_pdf)
    return made


ENTRY = BibEntry(key="23501", entry_type="techreport",
                 title="System architecture for the 5G System (Release 17)")


@pytest.mark.parametrize("key, title, number", [
    ("23501", "System architecture for the 5G System (Release 17)", "23.501"),
    ("3GPP_21905", "Vocabulary for 3GPP Specifications (Release 15)", "21.905"),
    ("3gpp_23.502", "Procedures for the 5G System (5GS)", "23.502"),
])
def test_a_spec_cited_by_its_bare_number_is_recognised(key, title, number):
    """A specification cited without "TR" or "TS" is still a specification,
    not an ordinary paper."""
    assert spec_number(title, key)[1] == number


def test_an_ordinary_paper_with_a_five_digit_key_is_not_a_spec():
    assert spec_number("Deep Learning for Crop Yield Prediction", "smith12345") is None


def test_the_latest_version_of_the_cited_release_is_downloaded(tmp_path, converts):
    zip_url = f"{ARCHIVE}23501-h30.zip"
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): _listing("h00", "h30", "i00", "j10")},
                          bytes_by_url={zip_url: _zip(("23501-h30.doc", b"word"))})

    result = ThreeGppResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "resolved", result.reason
    assert zip_url in fetcher.calls
    assert "V17.3.0" in result.reason
    assert converts["source"].name == "23501-h30.doc"


def test_with_no_release_named_the_latest_version_is_downloaded(tmp_path, converts):
    converts["cover"] = "3GPP TS 23.501 V19.1.0 (2024-12)"
    entry = BibEntry(key="3gpp_ts_23501", entry_type="techreport", title="System architecture, TS 23.501")
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): _listing("h00", "j10", "i00")},
                          bytes_by_url={f"{ARCHIVE}23501-j10.zip": _zip(("23501-j10.docx", b"w"))})

    result = ThreeGppResolver().resolve(entry, fetcher, tmp_path)

    assert result.status == "resolved", result.reason
    assert "V19.1.0" in result.reason


def test_a_member_cannot_be_written_outside_the_folder(tmp_path, converts):
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): _listing("h30")},
                          bytes_by_url={f"{ARCHIVE}23501-h30.zip":
                                        _zip(("../../escape.doc", b"word"))})

    ThreeGppResolver().resolve(ENTRY, fetcher, tmp_path / "staging")

    assert not (tmp_path / "escape.doc").exists()
    assert converts["source"].parent.is_relative_to(tmp_path / "staging")


def test_a_zip_that_would_unpack_to_something_huge_is_refused(tmp_path, converts, monkeypatch):
    monkeypatch.setattr(threegpp, "MAX_DOCUMENT_BYTES", 1000)
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): _listing("h30")},
                          bytes_by_url={f"{ARCHIVE}23501-h30.zip": _zip(("23501-h30.doc", b"0" * 5000))})

    result = ThreeGppResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status != "resolved"
    assert "source" not in converts


def test_a_conversion_showing_another_spec_is_not_kept(tmp_path, converts):
    converts["cover"] = "3GPP TS 36.211 V15.4.0 (2018-12)"
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): _listing("h30")},
                          bytes_by_url={f"{ARCHIVE}23501-h30.zip": _zip(("23501-h30.doc", b"w"))})

    result = ThreeGppResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status != "resolved"
    assert not list(tmp_path.glob("*.pdf"))


def test_without_libreoffice_nothing_is_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(threegpp, "converter", lambda: None)
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): _listing("h30")})

    result = ThreeGppResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "no-pdf"
    assert "LibreOffice" in result.reason
    assert fetcher.calls == []
    assert archive_url("23.501") in result.landing_pages


def test_an_archive_that_does_not_list_the_spec_leaves_the_link(tmp_path, converts):
    result = ThreeGppResolver().resolve(ENTRY, FakeFetcher(), tmp_path)

    assert result.status == "no-pdf"
    assert archive_url("23.501") in result.landing_pages


def test_an_archive_that_did_not_answer_keeps_the_link_and_asks_for_a_retry(tmp_path, converts):
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): _listing("h30")},
                          errors={f"{ARCHIVE}23501-h30.zip"})

    result = ThreeGppResolver().resolve(ENTRY, fetcher, tmp_path)

    assert result.retry and result.status == "no-pdf"
    assert archive_url("23.501") in result.landing_pages


@pytest.mark.parametrize("key, title", [
    ("3gpp_23501_rel17", "System architecture for the 5G System"),
    ("23501", "System architecture, Rel. 17"),
])
def test_a_release_named_in_the_key_or_abbreviated_is_honoured(tmp_path, converts, key, title):
    entry = BibEntry(key=key, entry_type="techreport", title=title)
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): _listing("h30", "j10")},
                          bytes_by_url={f"{ARCHIVE}23501-h30.zip": _zip(("23501-h30.doc", b"w")),
                                        f"{ARCHIVE}23501-j10.zip": _zip(("23501-j10.doc", b"w"))})

    result = ThreeGppResolver().resolve(entry, fetcher, tmp_path)

    assert "V17.3.0" in result.reason, result.reason


def test_an_exact_version_in_the_title_is_the_one_fetched(tmp_path, converts):
    converts["cover"] = "3GPP TS 23.501 V17.0.0 (2021-03)"
    entry = BibEntry(key="23501", entry_type="techreport", title="System architecture (3GPP TS 23.501 V17.0.0)")
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): _listing("h00", "h30")},
                          bytes_by_url={f"{ARCHIVE}23501-h00.zip": _zip(("23501-h00.doc", b"w"))})

    assert "V17.0.0" in ThreeGppResolver().resolve(entry, fetcher, tmp_path).reason


def test_a_spec_key_with_a_suffix_is_recognised():
    assert spec_number("Procedures for the 5G System (5GS)", "ts23502_rel16") == ("TS", "23.502")


def test_only_the_3gpp_archive_is_downloaded_from(tmp_path, converts):
    """A listing could point anywhere, and the highest version would win."""
    listing = (f'<a href="{ARCHIVE}23501-h30.zip">a</a>'
               '<a href="https://elsewhere.example/23501-j90.zip">b</a>')
    fetcher = FakeFetcher(text_by_url={archive_url("23.501"): listing},
                          bytes_by_url={f"{ARCHIVE}23501-h30.zip": _zip(("23501-h30.doc", b"w"))})

    ThreeGppResolver().resolve(BibEntry(key="23501", entry_type="techreport",
                                        title="System architecture, 3GPP"), fetcher, tmp_path)

    assert not any("elsewhere" in url for url in fetcher.calls)
