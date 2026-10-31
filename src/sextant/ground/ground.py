"""The spine: ask Claude about a document and verify every citation it returns."""

from collections.abc import Sequence

import anthropic

from sextant.ground.client import MODEL, PdfTooLargeError, document_block
from sextant.ground.recover import recover_span
from sextant.models import Evidence, GroundedAnswer, Page, Paper, Unverified

MAX_TOKENS = 8000


class GroundingError(RuntimeError):
    """A request to Claude failed or was declined.

    Exists so callers have one thing to catch. Without it a timeout, a 400, or
    a safety refusal propagates as a raw SDK exception through the CLI and out
    as a traceback — which contradicts the design's own rule that failure is
    data, not an exception. Plan 2's audit pipeline catches this per citation
    site and records it, so one bad request never aborts a whole audit.
    """


SYSTEM = (
    "You answer questions about the attached research paper. "
    "Quote the paper directly for every substantive claim you make. "
    "If the paper does not address the question, say so plainly rather than "
    "inferring an answer."
)


def ground(
    client,
    paper: Paper,
    pages: Sequence[Page],
    question: str,
    *,
    model: str = MODEL,
    effort: str = "high",
) -> GroundedAnswer:
    """Answer `question` about `paper`, with every citation verified.

    No `thinking` parameter is passed: adaptive thinking is on by default on
    claude-opus-5. Sampling parameters and `budget_tokens` are rejected by this
    model and are never sent. `output_config.format` is likewise never set — it
    is incompatible with citations and would 400.
    """
    # Built before the request so an oversized PDF surfaces as a GroundingError
    # like every other failure here, rather than escaping as a raw ValueError
    # past the CLI's handler.
    try:
        document = document_block(paper)
    except PdfTooLargeError as exc:
        raise GroundingError(str(exc)) from exc

    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            output_config={"effort": effort},
            messages=[
                {
                    "role": "user",
                    "content": [document, {"type": "text", "text": question}],
                }
            ],
        )
    except anthropic.APIError as exc:
        raise GroundingError(f"request to Claude failed: {exc}") from exc

    # Check stop_reason before reading content. A safety refusal returns a
    # successful HTTP 200 with empty or partial content, so code that indexes
    # response.content unconditionally breaks on it.
    if getattr(response, "stop_reason", None) == "refusal":
        raise GroundingError("Claude declined to answer this request.")

    texts: list[str] = []
    evidence: list[Evidence] = []
    unverified: list[Unverified] = []

    for block in response.content:
        if getattr(block, "type", None) != "text":
            continue

        texts.append(block.text)

        for citation in getattr(block, "citations", None) or []:
            if getattr(citation, "type", None) != "page_location":
                continue

            span = recover_span(
                pages,
                citation.start_page_number,
                citation.end_page_number,
                citation.cited_text,
            )
            if span is None:
                # Keep the claimed page range: it distinguishes "recovery
                # missed at the right page" from "model reported the wrong
                # page", which need different fixes.
                unverified.append(
                    Unverified(
                        cited_text=citation.cited_text,
                        start_page=citation.start_page_number,
                        end_page=citation.end_page_number,
                    )
                )
            else:
                evidence.append(Evidence(cited_text=citation.cited_text, span=span))

    return GroundedAnswer(
        text="".join(texts),
        evidence=tuple(evidence),
        unverified=tuple(unverified),
    )
