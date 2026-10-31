"""Relevance assessments computed ahead of being asked for.

A judgement costs a model call of roughly twenty seconds. Doing that when the
reader clicks means the reader waits; doing it for every citation the moment a
manuscript opens means they almost never do.

Deliberately in-process and lossy. These are opinions about a document, cheap
to recompute and worth nothing once the paper changes, so there is no reason
to put them on disk.
"""

import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

#: Judgements to run at once.
#:
#: Each is a separate `claude -p` process taking roughly twenty seconds, so
#: twenty citations took seven minutes in sequence -- long enough that the
#: answer was never ready when the reader arrived, which is the same as not
#: having it. Six at a time brings the same twenty under a minute. Kept modest
#: because these are real processes on the reader's own machine.
CONCURRENCY = 6

_lock = threading.Lock()
_results: dict[tuple[str, int], dict] = {}
#: The unargued judgement a revision displaced, so Revert has something exact
#: to put back. Same lifetime as the results themselves.
_superseded: dict[tuple[str, int], dict] = {}
_progress: dict[str, dict] = {}


def _settled(result: dict | None) -> bool:
    """True when a stored result is an answer rather than a failure to ask."""
    return result is not None and not result.get("failed")


def get(path: str, marker_id: int) -> dict | None:
    with _lock:
        return _results.get((path, marker_id))


def put(path: str, marker_id: int, result: dict) -> None:
    with _lock:
        _results[(path, marker_id)] = result


def revise(path: str, marker_id: int, result: dict) -> None:
    """Store a judgement made after the reader argued, keeping the one it
    replaced.

    Kept rather than recomputed: going back has to return the judgement that
    was actually there, not a fresh model call that may land somewhere else
    and would take twenty seconds to say so.

    Only an unargued judgement is ever put aside. Revising a second time
    replaces the first revision but leaves the original underneath, so Revert
    always reaches the assessment nobody argued for.
    """
    with _lock:
        key = (path, marker_id)
        current = _results.get(key)
        if key not in _superseded and _settled(current) and not current.get("revised"):
            _superseded[key] = current
        _results[key] = result


def revert(path: str, marker_id: int) -> dict | None:
    """Put back the judgement a revision replaced, or None if none was."""
    with _lock:
        key = (path, marker_id)
        previous = _superseded.pop(key, None)
        if previous is None:
            return None
        _results[key] = previous
        return previous


def progress(path: str) -> dict:
    with _lock:
        return dict(_progress.get(path) or {"done": 0, "total": 0, "running": False})


def forget(path: str) -> None:
    """Drop everything known about a manuscript, e.g. once its library changes."""
    with _lock:
        for key in [k for k in _results if k[0] == path]:
            del _results[key]
        for key in [k for k in _superseded if k[0] == path]:
            del _superseded[key]
        _progress.pop(path, None)


def run_in_background(
    path: str, marker_ids: Iterable[int], assess_one: Callable[[int], dict]
) -> dict:
    """Assess each marker on a worker thread, newest request wins.

    Returns immediately. Progress is readable while it runs, and each result
    is published as it lands rather than at the end, so a reader who clicks
    early gets whatever is ready.
    """
    # A result that never reached Claude is not an answer, so it does not
    # count as done. Without this one failed call was permanent: the marker
    # held a result, so every later pass skipped it.
    ids = [i for i in marker_ids if not _settled(get(path, i))]
    with _lock:
        if (_progress.get(path) or {}).get("running"):
            return dict(_progress[path])
        _progress[path] = {"done": 0, "total": len(ids), "running": bool(ids)}
        snapshot = dict(_progress[path])

    if not ids:
        return snapshot

    def judge(marker_id: int) -> None:
        try:
            put(path, marker_id, assess_one(marker_id))
        except Exception as exc:  # noqa: BLE001 - one failure must not stop the rest
            put(path, marker_id,
                {"verdict": "unclear", "why": f"assessment failed: {exc}",
                 "excerpts": [], "failed": True})
        with _lock:
            if path in _progress:
                _progress[path]["done"] += 1

    def worker() -> None:
        try:
            with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
                # list() so the pool is drained before the flag is cleared.
                list(pool.map(judge, ids))
        finally:
            with _lock:
                if path in _progress:
                    _progress[path]["running"] = False

    threading.Thread(target=worker, name=f"assess:{path}", daemon=True).start()
    return snapshot
