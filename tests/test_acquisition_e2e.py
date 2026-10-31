"""Offline end-to-end over a real LaTeX project of your own.

No network: these measure the parsing and plumbing against real files rather
than the resolvers themselves. The live Crossref variant is marked and
deselected by default — it needs network but no API key, and is free.
"""

import os
from pathlib import Path

import pytest

from sextant.refs.bibtex import parse_bib
from sextant.refs.http import HttpFetcher
from sextant.refs.latex import cited_keys_from_file
from sextant.refs.linkcheck import check_entry

#: A LaTeX project of the reader's own: a main.tex and the .bib files beside
#: it. No default -- one baked in named somebody's unpublished manuscript.
BASE = Path(os.environ["SEXTANT_TEST_PROJECT"]) if os.environ.get("SEXTANT_TEST_PROJECT") else None
TEX = (BASE / "main.tex") if BASE else None
_NO_PROJECT = not (TEX and TEX.exists())
_REASON = "set SEXTANT_TEST_PROJECT to a LaTeX project with a main.tex"


def _entries():
    entries = {}
    for bib in sorted(BASE.rglob("*.bib")):
        entries.update(parse_bib(bib.read_text(errors="ignore")))
    return entries


@pytest.mark.skipif(_NO_PROJECT, reason=_REASON)
def test_every_cited_key_is_found_in_the_bibliography():
    """The counts belong to whichever project you point this at, so what is
    asserted is the property: nothing is cited that no .bib defines."""
    keys = cited_keys_from_file(TEX)
    entries = _entries()

    assert keys, "no \\cite keys were found in the manuscript"
    missing = sorted(keys - entries.keys())
    assert missing == [], f"cited but not in any .bib: {missing}"


@pytest.mark.skipif(_NO_PROJECT, reason=_REASON)
def test_cited_entries_carry_dois_that_linkcheck_can_use():
    keys = cited_keys_from_file(TEX)
    entries = _entries()
    with_doi = [k for k in keys if entries.get(k) and entries[k].doi]

    assert with_doi, "no cited entry carried a DOI, so linkcheck has nothing to do"


@pytest.mark.skipif(_NO_PROJECT, reason=_REASON)
def test_no_inproceedings_entry_has_a_conference_name_as_its_title():
    """Regression guard for the booktitle trap."""
    for entry in _entries().values():
        if entry.entry_type == "inproceedings" and entry.title:
            assert not entry.title.strip().startswith("20"), (
                f"{entry.key}: title looks like a conference name: {entry.title!r}"
            )


@pytest.mark.live
@pytest.mark.skipif(_NO_PROJECT, reason=_REASON)
def test_link_check_against_the_live_crossref_api():
    """A mismatch here is a real finding: the .bib says one paper and the DOI
    resolves to another.

    Free — Crossref requires no key. Marked live only because it needs network.
    """
    import time

    keys = cited_keys_from_file(TEX)
    entries = _entries()
    fetcher = HttpFetcher()

    checks = []
    for key in sorted(keys):
        if key not in entries:
            continue
        checks.append(check_entry(entries[key], fetcher))
        time.sleep(0.25)

    mismatches = [c for c in checks if c.verdict == "mismatch"]
    assert not mismatches, "\n".join(
        f"{c.key}\n  .bib : {c.claimed}\n  DOI  : {c.actual}" for c in mismatches
    )
