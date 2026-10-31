"""Anthropic client construction and request-block helpers."""

import base64
import os
from pathlib import Path

import anthropic

from sextant.models import Paper

MODEL = "claude-opus-5"

# The Messages API caps a request at 32 MB. Base64 inflates by 4/3, so cap the
# raw PDF at 20 MB and leave headroom for the rest of the request.
MAX_INLINE_PDF_BYTES = 20 * 1024 * 1024


class MissingCredentialsError(RuntimeError):
    """Raised at startup when no API key is configured."""


class PdfTooLargeError(ValueError):
    """Raised when a PDF exceeds the inline base64 budget."""


def check_credentials() -> None:
    """Fail fast, with instructions, before any work begins."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise MissingCredentialsError(
            "ANTHROPIC_API_KEY is not set.\n"
            "Create a .env file in the directory you are running from:\n"
            "    ANTHROPIC_API_KEY=sk-ant-...\n"
            "Only `ask` needs a key. The viewer uses your Claude Code login.\n"
            "Get a key at https://console.anthropic.com/settings/keys"
        )


def build_client() -> anthropic.Anthropic:
    check_credentials()
    return anthropic.Anthropic()


def document_block(paper: Paper) -> dict:
    """A PDF document content block with citations enabled.

    This is the single seam where document delivery is decided. Swapping to
    the Files API (upload once, reference by file_id) touches only this
    function.
    """
    path = Path(paper.path)
    data = path.read_bytes()
    if len(data) > MAX_INLINE_PDF_BYTES:
        raise PdfTooLargeError(
            f"{path.name} is {len(data) / 1e6:.1f} MB, over the "
            f"{MAX_INLINE_PDF_BYTES / 1e6:.0f} MB inline limit."
        )

    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            # standard_b64encode emits no newlines; encodebytes would, and the
            # API rejects newlines in the base64 payload.
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
        "title": paper.title or path.name,
        "citations": {"enabled": True},
    }
