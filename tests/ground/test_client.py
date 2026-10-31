import base64

import pytest

from sextant.ground.client import (
    MAX_INLINE_PDF_BYTES,
    MissingCredentialsError,
    PdfTooLargeError,
    check_credentials,
    document_block,
)
from sextant.models import Paper


def test_check_credentials_raises_with_actionable_message(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingCredentialsError) as excinfo:
        check_credentials()
    assert ".env" in str(excinfo.value)


def test_check_credentials_passes_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    check_credentials()


def test_document_block_has_citations_enabled(sample_pdf):
    paper = Paper(id="abc", path=str(sample_pdf), content_hash="x", title="Sample")
    block = document_block(paper)

    assert block["type"] == "document"
    assert block["citations"] == {"enabled": True}
    assert block["title"] == "Sample"
    assert block["source"]["media_type"] == "application/pdf"


def test_document_block_base64_has_no_newlines(sample_pdf):
    paper = Paper(id="abc", path=str(sample_pdf), content_hash="x")
    data = document_block(paper)["source"]["data"]

    assert "\n" not in data
    assert base64.standard_b64decode(data)[:4] == b"%PDF"


def test_document_block_falls_back_to_filename_for_title(sample_pdf):
    paper = Paper(id="abc", path=str(sample_pdf), content_hash="x", title=None)
    assert document_block(paper)["title"] == "sample.pdf"


def test_oversized_pdf_is_rejected_with_a_clear_error(tmp_path):
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF" + b"0" * (MAX_INLINE_PDF_BYTES + 1))
    paper = Paper(id="abc", path=str(big), content_hash="x")

    with pytest.raises(PdfTooLargeError):
        document_block(paper)
