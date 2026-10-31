"""Judgements computed before they are asked for."""

import time

from sextant.chat import pending


def _wait(path, seconds=3.0):
    deadline = time.time() + seconds
    while time.time() < deadline and pending.progress(path)["running"]:
        time.sleep(0.02)



def test_results_land_as_they_are_computed(tmp_path):
    path = str(tmp_path / "a.pdf")
    pending.forget(path)

    pending.run_in_background(path, [0, 1], lambda i: {"verdict": f"v{i}"})
    _wait(path)

    assert pending.get(path, 0) == {"verdict": "v0"}
    assert pending.get(path, 1) == {"verdict": "v1"}


def test_progress_is_readable_while_it_runs(tmp_path):
    path = str(tmp_path / "b.pdf")
    pending.forget(path)

    started = pending.run_in_background(path, [0, 1, 2], lambda i: {"v": i})

    assert started["total"] == 3
    _wait(path)
    assert pending.progress(path)["done"] == 3
    assert pending.progress(path)["running"] is False


def test_one_failure_does_not_stop_the_rest(tmp_path):
    path = str(tmp_path / "c.pdf")
    pending.forget(path)

    def flaky(i):
        if i == 0:
            raise RuntimeError("claude unavailable")
        return {"verdict": "fine"}

    pending.run_in_background(path, [0, 1], flaky)
    _wait(path)

    assert pending.get(path, 0)["verdict"] == "unclear"
    assert "claude unavailable" in pending.get(path, 0)["why"]
    assert pending.get(path, 1)["verdict"] == "fine"


def test_work_already_done_is_not_repeated(tmp_path):
    path = str(tmp_path / "d.pdf")
    pending.forget(path)
    pending.put(path, 0, {"verdict": "cached"})

    calls = []
    pending.run_in_background(path, [0, 1], lambda i: calls.append(i) or {"v": i})
    _wait(path)

    assert calls == [1], "marker 0 was already judged"


def test_forgetting_a_manuscript_drops_its_judgements(tmp_path):
    path = str(tmp_path / "e.pdf")
    pending.put(path, 0, {"verdict": "x"})

    pending.forget(path)

    assert pending.get(path, 0) is None


def test_judgements_are_kept_per_manuscript(tmp_path):
    a, b = str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")
    pending.forget(a); pending.forget(b)
    pending.put(a, 0, {"verdict": "for a"})

    assert pending.get(b, 0) is None


def test_judgements_run_concurrently(tmp_path):
    """Twenty at twenty seconds each is seven minutes in sequence -- long
    enough that the answer is never ready when the reader arrives."""
    import threading

    path = str(tmp_path / "par.pdf")
    pending.forget(path)

    live, peak = [0], [0]
    guard = threading.Lock()

    def slow(i):
        with guard:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.15)
        with guard:
            live[0] -= 1
        return {"verdict": str(i)}

    pending.run_in_background(path, list(range(12)), slow)
    _wait(path, seconds=8)

    assert peak[0] > 1, "ran one at a time"
    assert peak[0] <= pending.CONCURRENCY
    assert all(pending.get(path, i) is not None for i in range(12))


def test_running_stays_true_until_every_judgement_lands(tmp_path):
    path = str(tmp_path / "flag.pdf")
    pending.forget(path)

    def slow(i):
        time.sleep(0.1)
        return {"verdict": "x"}

    pending.run_in_background(path, list(range(8)), slow)
    _wait(path, seconds=8)

    p = pending.progress(path)
    assert p["running"] is False and p["done"] == 8


def test_a_failed_assessment_is_retried_not_cached_forever():
    """One unreachable call must not stick to a citation for the life of the
    workspace. The marker held a result, so every later pass skipped it and
    the reader saw "could not reach Claude" permanently."""
    pending.forget("m.pdf")
    calls = []

    def flaky(marker_id: int) -> dict:
        calls.append(marker_id)
        if len(calls) == 1:
            return {"verdict": "unclear", "why": "could not reach Claude: boom",
                    "failed": True}
        return {"verdict": "related", "why": "second time lucky", "score": 3}

    pending.run_in_background("m.pdf", [7], flaky)
    _wait("m.pdf")
    assert pending.get("m.pdf", 7)["failed"] is True

    pending.run_in_background("m.pdf", [7], flaky)
    _wait("m.pdf")
    assert pending.get("m.pdf", 7)["verdict"] == "related"
    assert calls == [7, 7]


def test_a_real_answer_is_not_recomputed():
    """The retry must not turn into re-asking every citation on every pass."""
    pending.forget("m.pdf")
    calls = []

    def once(marker_id: int) -> dict:
        calls.append(marker_id)
        return {"verdict": "supports", "score": 5}

    pending.run_in_background("m.pdf", [1], once)
    _wait("m.pdf")
    pending.run_in_background("m.pdf", [1], once)
    _wait("m.pdf")

    assert calls == [1]


def test_a_revision_keeps_the_judgement_it_replaced(tmp_path):
    """Revert has to return what was actually there. Recomputing would take
    twenty seconds and could land somewhere else again."""
    path = str(tmp_path / "revise.pdf")
    pending.forget(path)

    pending.put(path, 0, {"score": 2, "why": "thin"})
    pending.revise(path, 0, {"score": 4, "why": "the note explains it", "revised": True})

    assert pending.get(path, 0)["score"] == 4
    assert pending.revert(path, 0) == {"score": 2, "why": "thin"}
    assert pending.get(path, 0) == {"score": 2, "why": "thin"}


def test_revising_twice_still_reverts_to_the_unargued_judgement(tmp_path):
    """Otherwise a second argument buries the original under the first one,
    and Revert only ever walks back to another thing you argued for."""
    path = str(tmp_path / "twice.pdf")
    pending.forget(path)

    pending.put(path, 0, {"score": 1})
    pending.revise(path, 0, {"score": 3, "revised": True})
    pending.revise(path, 0, {"score": 5, "revised": True})

    assert pending.revert(path, 0) == {"score": 1}


def test_reverting_what_was_never_argued_says_so(tmp_path):
    path = str(tmp_path / "plain.pdf")
    pending.forget(path)

    pending.put(path, 0, {"score": 3})

    assert pending.revert(path, 0) is None
    assert pending.get(path, 0) == {"score": 3}


def test_forgetting_a_manuscript_drops_what_it_was_holding_back(tmp_path):
    """A stale original outliving its manuscript would be restored onto a
    judgement it has nothing to do with."""
    path = str(tmp_path / "gone.pdf")
    pending.forget(path)

    pending.put(path, 0, {"score": 2})
    pending.revise(path, 0, {"score": 4, "revised": True})
    pending.forget(path)

    assert pending.revert(path, 0) is None
