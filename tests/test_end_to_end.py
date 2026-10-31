"""Live test. Requires ANTHROPIC_API_KEY and spends roughly $0.10 per run.

    uv run pytest -m live -v

Skipped by default via the `addopts` in pyproject.toml, so the ordinary suite
stays fast, offline, and free.

This is the only test that exercises the grounding invariant against a real
typeset paper — real ligatures, real hyphenation, real column breaks — and
the only one that calls the API. Everything else runs against a generated
two-page fixture.
"""

import os
from pathlib import Path

import pytest

from sextant.ground.client import build_client
from sextant.ground.ground import ground
from sextant.index.extract import extract_pages
from sextant.models import Paper

#: No default: a path baked in here said whose machine this was written on,
#: and named the paper being written.
REAL_PAPER = (
    Path(os.environ["SEXTANT_TEST_PAPER"]) if os.environ.get("SEXTANT_TEST_PAPER") else None
)

MIN_RECOVERY_RATE = 0.8


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="no API key")
@pytest.mark.skipif(not (REAL_PAPER and REAL_PAPER.exists()),
                    reason="set SEXTANT_TEST_PAPER to a real paper")
def test_real_paper_produces_verified_evidence():
    pages = extract_pages(REAL_PAPER)
    paper = Paper(id="live", path=str(REAL_PAPER), content_hash="live")

    answer = ground(
        build_client(),
        paper,
        pages,
        "What system does this paper propose, and what are its main assumptions?",
    )

    assert answer.text, "no answer text returned"
    assert answer.evidence, (
        "the API returned no verifiable citations — either citations are not "
        "enabled on the request, or span recovery failed for every one"
    )

    # THE INVARIANT, against a real typeset paper: every piece of evidence
    # must re-slice to real text at the recovered span, with rectangles to
    # highlight. A span that cannot do this is exactly the silently-wrong
    # highlight the whole design exists to prevent.
    for item in answer.evidence:
        page = next(p for p in pages if p.number == item.span.page)
        sliced = page.text[item.span.char_start : item.span.char_end]
        assert sliced.strip(), f"empty slice for {item.cited_text!r}"
        assert item.span.rects, f"no rectangles for {item.cited_text!r}"

    total = len(answer.evidence) + len(answer.unverified)
    rate = len(answer.evidence) / total
    assert rate >= MIN_RECOVERY_RATE, (
        f"only {len(answer.evidence)}/{total} citations recovered "
        f"({rate:.0%}, want >={MIN_RECOVERY_RATE:.0%}).\n"
        + "\n".join(
            f"  unrecovered, model claimed p.{u.start_page}: {u.cited_text!r}"
            for u in answer.unverified
        )
    )
