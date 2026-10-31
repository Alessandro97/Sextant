"""Wrap a Fetcher so repeated requests hit SQLite instead of the network.

Negative results are cached deliberately. The manual acquisition loop is
fetch → read MISSING.md → download a few by hand → re-run, so without this
every pass re-requests the same misses from the same APIs.

Downloads are never cached: a PDF either landed on disk or it did not, the
filesystem already answers that, and a stale "yes" would hide a missing file.
"""

import json
import time
from pathlib import Path

from sextant.refs.http import Fetcher
from sextant.store.db import Store

DEFAULT_TTL = 7 * 24 * 3600  # a week; bibliographies do not change fast
_MISS = "\x00miss"


class CachingFetcher:
    def __init__(
        self, inner: Fetcher, store: Store, ttl_seconds: float = DEFAULT_TTL
    ) -> None:
        self._inner = inner
        self._conn = store._conn  # same connection, same transaction scope
        self._ttl = ttl_seconds

    def json(self, url: str) -> dict | None:
        hit = self._get(url, "json")
        if hit is not None:
            return None if hit == _MISS else json.loads(hit)

        result = self._inner.json(url)
        self._put(url, "json", _MISS if result is None else json.dumps(result))
        return result

    def text(self, url: str) -> str | None:
        hit = self._get(url, "text")
        if hit is not None:
            return None if hit == _MISS else hit

        result = self._inner.text(url)
        self._put(url, "text", _MISS if result is None else result)
        return result

    def download(self, url: str, dest: Path, expect: bytes = b"%PDF") -> bool:
        return self._inner.download(url, dest, expect)

    def _get(self, url: str, kind: str) -> str | None:
        row = self._conn.execute(
            "SELECT body, fetched_at FROM http_cache WHERE url = ? AND kind = ?",
            (url, kind),
        ).fetchone()
        if row is None:
            return None
        if time.time() - row["fetched_at"] > self._ttl:
            return None
        return row["body"]

    def _put(self, url: str, kind: str, body: str) -> None:
        self._conn.execute(
            "INSERT INTO http_cache (url, kind, body, fetched_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(url, kind) DO UPDATE SET "
            "  body = excluded.body, fetched_at = excluded.fetched_at",
            (url, kind, body, time.time()),
        )
        self._conn.commit()
