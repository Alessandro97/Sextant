"""Pull cited keys out of a LaTeX manuscript."""

import re
from pathlib import Path

_CITE = re.compile(
    r"\\(?:cite|citep|citet|citealp|autocite|parencite)\*?\s*(?:\[[^\]]*\])*\s*\{([^}]*)\}"
)
_INPUT = re.compile(r"\\(?:input|include)\s*\{([^}]*)\}")
_COMMENT = re.compile(r"(?<!\\)%.*$", re.M)


def cited_keys(text: str) -> set[str]:
    """Every citation key in one document's source, multi-key expanded."""
    text = _COMMENT.sub("", text)
    keys: set[str] = set()
    for match in _CITE.finditer(text):
        for key in match.group(1).split(","):
            key = key.strip()
            if key:
                keys.add(key)
    return keys


def cited_keys_from_file(path: Path | str, _seen: set[Path] | None = None) -> set[str]:
    """As cited_keys, following \\input and \\include one file at a time.

    A missing or unreadable subfile is skipped rather than raising: a
    manuscript that does not fully build is still worth auditing.
    """
    path = Path(path).resolve()
    seen = _seen if _seen is not None else set()
    if path in seen or not path.is_file():
        return set()
    seen.add(path)

    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return set()

    keys = cited_keys(text)

    stripped = _COMMENT.sub("", text)
    for match in _INPUT.finditer(stripped):
        name = match.group(1).strip()
        child = path.parent / name
        if child.suffix != ".tex":
            child = child.with_suffix(".tex")
        keys |= cited_keys_from_file(child, seen)

    return keys
