from sextant.refs.cache import CachingFetcher
import pytest

from sextant.refs.http import FakeFetcher, Unavailable
from sextant.store.db import Store


def test_a_second_identical_request_does_not_reach_the_network(tmp_path):
    store = Store.open(tmp_path / "p.db")
    inner = FakeFetcher(json_by_url={"https://x/1": {"ok": True}})
    cached = CachingFetcher(inner, store)

    assert cached.json("https://x/1") == {"ok": True}
    assert cached.json("https://x/1") == {"ok": True}
    assert inner.calls == ["https://x/1"]
    store.close()


def test_negative_results_are_cached_too(tmp_path):
    """The manual loop re-runs fetch repeatedly; without this, every pass
    re-requests the same misses."""
    store = Store.open(tmp_path / "p.db")
    inner = FakeFetcher()
    cached = CachingFetcher(inner, store)

    assert cached.json("https://missing") is None
    assert cached.json("https://missing") is None
    assert inner.calls == ["https://missing"]
    store.close()


def test_an_expired_entry_is_refetched(tmp_path):
    store = Store.open(tmp_path / "p.db")
    inner = FakeFetcher(json_by_url={"https://x/1": {"v": 1}})
    cached = CachingFetcher(inner, store, ttl_seconds=-1)

    cached.json("https://x/1")
    cached.json("https://x/1")
    assert len(inner.calls) == 2
    store.close()


def test_downloads_are_never_cached(tmp_path):
    """A PDF either landed on disk or it did not — the filesystem is the
    cache, and a stale 'yes' would hide a missing file."""
    store = Store.open(tmp_path / "p.db")
    inner = FakeFetcher(bytes_by_url={"https://x/p.pdf": b"%PDF-1.7"})
    cached = CachingFetcher(inner, store)

    cached.download("https://x/p.pdf", tmp_path / "a.pdf")
    cached.download("https://x/p.pdf", tmp_path / "b.pdf")

    assert len(inner.calls) == 2
    assert (tmp_path / "b.pdf").exists()
    store.close()


def test_cache_survives_reopening_the_store(tmp_path):
    inner = FakeFetcher(json_by_url={"https://x/1": {"ok": True}})

    store = Store.open(tmp_path / "p.db")
    CachingFetcher(inner, store).json("https://x/1")
    store.close()

    store = Store.open(tmp_path / "p.db")
    assert CachingFetcher(inner, store).json("https://x/1") == {"ok": True}
    assert len(inner.calls) == 1
    store.close()


def test_text_and_json_are_cached_separately(tmp_path):
    """Same URL, different accessor — must not collide."""
    store = Store.open(tmp_path / "p.db")
    inner = FakeFetcher(json_by_url={"https://x": {"a": 1}}, text_by_url={"https://x": "hi"})
    cached = CachingFetcher(inner, store)

    assert cached.json("https://x") == {"a": 1}
    assert cached.text("https://x") == "hi"
    store.close()


def test_a_source_that_could_not_be_asked_is_asked_again(tmp_path):
    """A 429 cached as a miss hid papers for a week: a rerun the same day
    reported the same "no matching arxiv entry" without asking arXiv."""
    store = Store.open(tmp_path / "p.db")
    inner = FakeFetcher(errors={"https://busy"})
    cached = CachingFetcher(inner, store)

    for _ in range(2):
        with pytest.raises(Unavailable):
            cached.json("https://busy")
        with pytest.raises(Unavailable):
            cached.text("https://busy")
    assert inner.calls == ["https://busy"] * 4
    store.close()
