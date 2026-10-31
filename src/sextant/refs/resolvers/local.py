"""Check the papers already on disk before asking the internet.

A researcher keeps hundreds of PDFs scattered across project directories. Some
fraction of any bibliography is already among them, and finding it costs
nothing.
"""

from pathlib import Path

from sextant.refs.http import Fetcher
from sextant.refs.models import BibEntry, Resolution
from sextant.refs.titles import canonical_title, titles_match
from sextant.store.db import Store


class LocalResolver:
    name = "local"

    def __init__(self, store: Store) -> None:
        self._store = store

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution:
        if not entry.title:
            return Resolution(key=entry.key, status="unresolved",
                              reason="entry has no title to match on")

        matching = [paper for paper in self._store.list_papers()
                    if titles_match(entry.title, paper.title)]
        if not matching:
            return Resolution(key=entry.key, status="unresolved",
                              reason="no local copy")

        # "Coastal Erosion Models" is the main title of two different papers
        # with two different subtitles. Which one is cited cannot be told from
        # the title, so neither is.
        if len({canonical_title(paper.title) for paper in matching}) > 1:
            return Resolution(key=entry.key, status="unresolved",
                              reason=f"{len(matching)} local papers answer to this title")
        paper = matching[0]

        # Registered is not the same as present. Never hand back a path
        # that has moved or been deleted.
        stale = self._store.staleness(paper)
        if stale is not None:
            return Resolution(key=entry.key, status="unresolved",
                              reason=f"local copy {stale}")

        return Resolution(key=entry.key, status="resolved", title=paper.title,
                          pdf_path=paper.path, resolver=self.name)
