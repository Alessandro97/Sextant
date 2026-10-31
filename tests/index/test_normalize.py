from sextant.index.normalize import INVISIBLE, normalize


def _check(original: str) -> tuple[str, list[int]]:
    """Run normalize and assert its invariant on every call.

    The invariant is the module's whole contract, but it was previously
    asserted in one trivial test while the ligature and hyphenation paths
    discarded offsets with `_`. That is exactly where an offset bug hides —
    and one did.
    """
    out, offsets = normalize(original)
    assert len(out) == len(offsets), (
        f"invariant broken: {len(out)} chars vs {len(offsets)} offsets"
    )
    for k, offset in enumerate(offsets):
        assert 0 <= offset < len(original), (
            f"offsets[{k}]={offset} out of range for input of length {len(original)}"
        )
    assert offsets == sorted(offsets), "offsets must be non-decreasing"
    return out, offsets


def test_collapses_whitespace_and_lowercases():
    out, offsets = _check("The   Quick\n\tBrown")
    assert out == "the quick brown"
    assert len(offsets) == len(out)


def test_expands_ligatures():
    out, _ = _check("eﬃcient ﬁlter ﬂow")
    assert out == "efficient filter flow"


def test_joins_line_break_hyphenation():
    out, _ = _check("through-\nput")
    assert out == "throughput"


def test_keeps_hyphen_when_next_word_is_capitalised():
    out, _ = _check("X-\nRay")
    assert out == "x- ray"


def test_normalises_dashes_and_smart_quotes():
    out, _ = _check("“en–dash” and ’apostrophe")
    assert out == '"en-dash" and \'apostrophe'


def test_offsets_map_back_to_original_indices():
    original = "The   quick"
    out, offsets = _check(original)
    assert out == "the quick"
    # 'q' is at normalized index 4; in the original it sits at index 6
    assert out[4] == "q"
    assert original[offsets[4]] == "q"


def test_empty_and_whitespace_only_input():
    assert _check("") == ("", [])
    assert _check("   \n\t ") == ("", [])


def test_lowercasing_can_expand_a_character_and_offsets_stay_aligned():
    """str.lower() is not always 1:1 — "İ" lowercases to two code points.

    Before this was fixed, offsets did not expand with it, so every later
    span shifted by one: recover_span returned a non-None Span slicing
    'ggregate write throughput ' for a citation of 'aggregate write
    throughput', and a nearby input raised IndexError.
    """
    assert len("İ".lower()) == 2  # the premise, in case CPython ever changes it
    out, _ = _check("Sample İstanbul text")
    assert "istanbul" in out.replace("̇", "")


def test_dehyphenation_accepts_every_dash_this_module_folds():
    for dash in ("-", "‐", "‑", "‒", "–", "—", "−"):
        out, _ = _check(f"through{dash}\nput")
        assert out == "throughput", f"failed for U+{ord(dash):04X}"


def test_folds_invisible_characters():
    assert _check("docu­ment")[0] == "document"
    assert _check("note​book")[0] == "notebook"
    assert _check("zero‍width")[0] == "zerowidth"


def test_a_deleting_replacement_is_not_skipped_by_lookup():
    """Guards against reintroducing the `.get() or .get()` chain.

    An `or` chain picks the first truthy value, so a mapping to "" is falsy,
    falls through, and the character passes through verbatim — the opposite
    of deleting it.
    """
    for ch in INVISIBLE:
        assert ch not in _check(f"a{ch}b")[0]
