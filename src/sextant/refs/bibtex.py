"""Parse .bib files well enough for acquisition.

Deliberately not a full BibTeX implementation. It reads the handful of fields
acquisition needs from real, messy files: inconsistent entry-type casing,
brace-wrapped values, control entries, and @inproceedings entries that carry
both `title` and `booktitle`.
"""

import re

from sextant.refs.models import BibEntry

# Entry types that carry no bibliographic data.
CONTROL_TYPES = {"ieeetranbstctl", "preamble", "comment", "string"}

# The key class excludes { } and @ deliberately. Allowing them lets a
# truncated "@article{" with no key swallow the NEXT entry's header as its
# own key, silently losing that entry.
_ENTRY = re.compile(r"@([a-zA-Z]+)\s*\{\s*([^,\s{}@]+)\s*,", re.M)


def parse_bib(text: str) -> dict[str, BibEntry]:
    """Return {citation key: BibEntry}. Malformed entries are skipped."""
    entries: dict[str, BibEntry] = {}
    starts = [(m.start(), m.group(1).lower(), m.group(2)) for m in _ENTRY.finditer(text)]

    for i, (pos, entry_type, key) in enumerate(starts):
        if entry_type in CONTROL_TYPES:
            continue
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        body = text[pos:end]
        entries[key] = BibEntry(
            key=key,
            entry_type=entry_type,
            title=_field(body, "title"),
            doi=_field(body, "doi"),
            year=_field(body, "year"),
            authors=_field(body, "author"),
            url=_field(body, "url"),
        )

    return entries


def _field(body: str, name: str) -> str | None:
    """Extract one field's value.

    The leading (?<![a-zA-Z]) is load-bearing: without it, `title` also matches
    `booktitle`, and every @inproceedings entry ends up with the conference
    name where its paper title should be.
    """
    match = re.search(rf"(?<![a-zA-Z]){name}\s*=\s*", body, re.I)
    if match is None:
        return None

    rest = body[match.end() :].lstrip()
    if not rest:
        return None

    value = _balanced(rest)
    if value is None:
        return None

    value = value.replace("{", "").replace("}", "")
    value = " ".join(value.split())
    return value or None


def _balanced(rest: str) -> str | None:
    """Read a {braced}, "quoted", or bare value from the start of `rest`."""
    if rest[0] == "{":
        depth = 0
        for i, ch in enumerate(rest):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return rest[1:i]
        return None

    if rest[0] == '"':
        end = rest.find('"', 1)
        return rest[1:end] if end != -1 else None

    end = re.search(r"[,\n}]", rest)
    return rest[: end.start()] if end else rest
