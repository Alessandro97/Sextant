"""Materialize resolutions as a browsable folder beside the manuscript.

The store keeps content-addressed blobs so a paper cited from three
manuscripts is stored once. A hash is not browsable, so this writes a symlink
farm named by citation key that opens in an ordinary PDF reader.
"""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Sequence

from sextant.refs.models import Resolution
from sextant.safefs import real_dir, write_file


def refs_dir(manuscript: Path | str) -> Path:
    return Path(manuscript).resolve().parent / "refs"


#: What no filename here may hold: a path separator, NUL or a control
#: character, and on Windows its own reserved punctuation as well.
_FORBIDDEN = re.compile(
    r"[/\\\x00-\x1f\x7f" + (r'<>:"|?*' if os.name == "nt" else "") + "]")
#: For the readable part of a name made safe.
_UNSAFE = re.compile(r"[^\w.+-]")
#: Names Windows refuses for a file, whatever the extension.
_RESERVED = {"con", "prn", "aux", "nul",
             *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}


def _plain(key: str) -> bool:
    """Can `key` be a filename on this system as it stands?

    Not only letters and digits: Smith:2020 and "smith & jones" are keys
    people write, and refs/ folders made before keys were made safe already
    hold refs/Smith:2020.pdf. Renaming those hid the paper -- verified became
    no-source. What a filename cannot hold, or would hide (a leading dot) or
    lose (a trailing dot), still gets a safe name.
    """
    return (bool(key) and not key.startswith(".") and not key.endswith((".", " "))
            and not _FORBIDDEN.search(key)
            and not (os.name == "nt" and key.split(".")[0].lower() in _RESERVED))


def key_pdf(folder: Path, key: str) -> Path:
    """Where the PDF for citation `key` lives inside `folder`.

    Keys come from the manuscript, and a manuscript can be anyone's: a hyperref
    destination reading cite.../../thesis is a key like any other. A key that
    can be a filename keeps its own name, so existing refs/ folders still line
    up. Any other has its unsafe characters replaced, plus a hash of the
    original so that a/b and a_b do not end up sharing a file.
    """
    if _plain(key):
        return Path(folder) / f"{key}.pdf"
    readable = _UNSAFE.sub("_", key).strip("._") or "ref"
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return Path(folder) / f"{readable}-{digest}.pdf"


def downloads_dir(out: Path) -> Path:
    """Where resolvers write fetched PDFs.

    Deliberately NOT the refs folder itself. A resolver naming its download
    "{key}.pdf" in the same directory the symlink farm uses means the link
    path and the source path are the same file — and materialize would delete
    the download and leave a symlink pointing at itself.
    """
    return out / ".downloads"


def materialize(resolutions: Sequence[Resolution], out: Path) -> None:
    # A folder someone sent can ship any of these as a link. Refused, rather
    # than writing a report or a symlink farm wherever the link points.
    real_dir(out)
    real_dir(out / "inbox")
    real_dir(downloads_dir(out))

    for resolution in resolutions:
        if not resolution.pdf_path:
            continue

        target = Path(resolution.pdf_path).resolve()
        link = key_pdf(out, resolution.key)

        # Only ever replace a link this function made. A real file here is
        # either the download itself (the deliverable) or a copy someone keeps
        # in refs/, annotations and all, which is in no store and would be gone
        # for good.
        if link.exists() and not link.is_symlink():
            continue

        if link.is_symlink():
            link.unlink()
        link.symlink_to(target)

    write_file(out / "MISSING.md",
               _missing_report(resolutions) + _stand_in_report(_stand_ins(resolutions, out)))


#: Which filed copies are not the published version, kept beside them: the
#: next run finds such a copy locally and no longer knows where it came from.
STAND_INS_FILE = ".sextant-stand-ins.json"
_STAND_IN = {"submittedVersion", "acceptedVersion"}


def _stand_ins(resolutions: Sequence[Resolution], out: Path) -> dict[str, str]:
    """Key -> why its filed copy is not the published version."""
    path = out / STAND_INS_FILE
    try:
        notes = json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else {}
        notes = {k: v for k, v in notes.items() if isinstance(v, str)}
    except (OSError, ValueError, AttributeError):
        notes = {}
    for r in resolutions:
        if not r.pdf_path:
            notes.pop(r.key, None)
        elif r.version in _STAND_IN:
            notes[r.key] = r.reason or r.version
        elif r.resolver != "local":
            notes.pop(r.key, None)  # a published copy replaced it
    write_file(path, json.dumps(notes, indent=2, sort_keys=True))
    return notes


#: A link worth offering a person: the web, and nothing a renderer could
#: mistake for more than one link.
_WEB_LINK = re.compile(r"https?://[^\s<>\"'`]+")
_DOI = re.compile(r"10\.\d{4,9}/[^\s<>\"'`]+")
_MARKUP = str.maketrans({"\\": "\\\\", "<": "&lt;", ">": "&gt;", "[": "\\[", "]": "\\]",
                         "`": "'"})


def _text(value: str | None) -> str:
    """Metadata as one inert line: it comes from someone else's records, and
    a title holding a newline added fake entries to this file."""
    return " ".join(str(value or "").split()).translate(_MARKUP)


def _link(url: str | None) -> str | None:
    url = (url or "").strip()
    return f"<{url}>" if _WEB_LINK.fullmatch(url) else None


def _stand_in_report(notes: dict[str, str]) -> str:
    if not notes:
        return ""
    lines = ["", "# Filed in place of the published version", "",
             "A preprint or accepted manuscript can differ from the published",
             "paper in exactly the pages, figures and numbers a citation is",
             "checked against. Replace it with the published PDF when you can.", ""]
    lines += [f"- `{_text(key)}` — {_text(note)}" for key, note in sorted(notes.items())]
    return "\n".join(lines) + "\n"


def _missing_report(resolutions: Sequence[Resolution]) -> str:
    missing = [r for r in resolutions if not r.pdf_path]
    lines = [
        "# Missing references",
        "",
        "Fetch these by hand and drop them in `inbox/`. No renaming needed —",
        "each file is matched to a citation key by the title and DOI printed",
        "on its own first page.",
        "",
    ]

    if not missing:
        lines.append("Nothing missing. Every cited reference resolved.")
        return "\n".join(lines) + "\n"

    for r in sorted(missing, key=lambda x: x.key):
        lines.append(f"## `{_text(r.key)}`")
        if r.title:
            lines.append(f"- **Title:** {_text(r.title)}")
        if r.doi and _DOI.fullmatch(r.doi.strip()):
            doi = r.doi.strip()
            lines.append(f"- **DOI:** `{doi}` — <https://doi.org/{doi}>")
        for page in filter(None, map(_link, r.landing_pages)):
            lines.append(f"- **Repository copy:** {page}")
        for copy in r.similar:
            title, _, url = copy.rpartition(" — ")
            if _link(url):
                lines.append(f"- **Possibly the same work, titled differently:** "
                             f"{_text(title)} — {_link(url)}")
        if r.reason:
            lines.append(f"- *Tried:* {_text(r.reason)}")
        lines.append("")

    return "\n".join(lines) + "\n"
