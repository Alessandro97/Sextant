from types import SimpleNamespace

import anthropic
import pytest

from sextant.ground.client import MAX_INLINE_PDF_BYTES
from sextant.ground.ground import GroundingError, ground
from sextant.index.extract import extract_pages
from sextant.models import Paper


def _citation(cited_text, start, end):
    return SimpleNamespace(
        type="page_location",
        cited_text=cited_text,
        start_page_number=start,
        end_page_number=end,
    )


def _text_block(text, citations=None):
    return SimpleNamespace(type="text", text=text, citations=citations)


class FakeClient:
    """Stands in for anthropic.Anthropic, recording the request it received."""

    def __init__(self, blocks=None, stop_reason=None, raises=None):
        self._blocks = blocks or []
        self._stop_reason = stop_reason
        self._raises = raises
        self.request = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.request = kwargs
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(content=self._blocks, stop_reason=self._stop_reason)


def test_verified_citation_becomes_evidence(sample_pdf):
    pages = extract_pages(sample_pdf)
    paper = Paper(id="a", path=str(sample_pdf), content_hash="h")
    client = FakeClient(
        [_text_block("Yes.", [_citation("aggregate write throughput", 1, 1)])]
    )

    answer = ground(client, paper, pages, "Does it state a throughput?")

    assert answer.text == "Yes."
    assert len(answer.evidence) == 1
    assert answer.evidence[0].span.page == 1
    assert answer.unverified == ()


def test_unrecoverable_citation_is_surfaced_not_dropped(sample_pdf):
    pages = extract_pages(sample_pdf)
    paper = Paper(id="a", path=str(sample_pdf), content_hash="h")
    client = FakeClient(
        [_text_block("Yes.", [_citation("text that is not in the document", 1, 1)])]
    )

    answer = ground(client, paper, pages, "?")

    assert answer.evidence == ()
    assert len(answer.unverified) == 1
    assert answer.unverified[0].cited_text == "text that is not in the document"
    assert answer.unverified[0].start_page == 1
    assert answer.unverified[0].end_page == 1


def test_text_blocks_without_citations_still_contribute_text(sample_pdf):
    pages = extract_pages(sample_pdf)
    paper = Paper(id="a", path=str(sample_pdf), content_hash="h")
    client = FakeClient([_text_block("Part one. "), _text_block("Part two.")])

    answer = ground(client, paper, pages, "?")

    assert answer.text == "Part one. Part two."
    assert answer.evidence == ()


def test_non_text_blocks_are_ignored(sample_pdf):
    pages = extract_pages(sample_pdf)
    paper = Paper(id="a", path=str(sample_pdf), content_hash="h")
    client = FakeClient(
        [SimpleNamespace(type="thinking", thinking=""), _text_block("Answer.")]
    )

    answer = ground(client, paper, pages, "?")
    assert answer.text == "Answer."


def test_request_enables_citations_and_omits_forbidden_params(sample_pdf):
    """citations is incompatible with output_config.format; sampling params 400."""
    pages = extract_pages(sample_pdf)
    paper = Paper(id="a", path=str(sample_pdf), content_hash="h")
    client = FakeClient([_text_block("ok")])

    ground(client, paper, pages, "?")

    request = client.request
    document = request["messages"][0]["content"][0]
    assert document["citations"] == {"enabled": True}
    assert "format" not in request.get("output_config", {})
    for forbidden in ("temperature", "top_p", "top_k", "thinking"):
        assert forbidden not in request


def test_api_failure_becomes_grounding_error(sample_pdf):
    """A raw SDK exception must not reach the CLI as a traceback."""
    pages = extract_pages(sample_pdf)
    paper = Paper(id="a", path=str(sample_pdf), content_hash="h")
    client = FakeClient(raises=anthropic.APIConnectionError(request=None))

    with pytest.raises(GroundingError):
        ground(client, paper, pages, "?")


def test_refusal_is_reported_rather_than_indexed_into(sample_pdf):
    """stop_reason 'refusal' returns HTTP 200 with empty content."""
    pages = extract_pages(sample_pdf)
    paper = Paper(id="a", path=str(sample_pdf), content_hash="h")
    client = FakeClient([], stop_reason="refusal")

    with pytest.raises(GroundingError):
        ground(client, paper, pages, "?")


def test_oversized_pdf_becomes_a_grounding_error(tmp_path, sample_pdf):
    """PdfTooLargeError must not escape past the CLI's GroundingError handler.

    document_block() is built before the request precisely so this surfaces
    like every other failure here rather than as a raw ValueError.
    """
    pages = extract_pages(sample_pdf)
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF" + b"0" * (MAX_INLINE_PDF_BYTES + 1))
    paper = Paper(id="a", path=str(big), content_hash="h")
    client = FakeClient([_text_block("unreachable")])

    with pytest.raises(GroundingError):
        ground(client, paper, pages, "?")

    assert client.request is None, "the request must not have been attempted"
