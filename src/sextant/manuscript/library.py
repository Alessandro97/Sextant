"""Where a manuscript's reference library lives.

Two folders, kept apart on purpose: the manuscript is one file, the library is
a directory of the papers it cites. They are usually siblings, but not always
-- a PDF uploaded through the browser has no folder of its own, because a
browser sends bytes and a filename and never a path.

The choice is recorded so every route agrees on it without the browser having
to resend it, and so it survives a restart. It used to be recorded beside the
manuscript, in .sextant-library, and read back from there -- a file a folder
someone sent can ship as well. One reading ~/.bashrc.d had Sextant write its
report where Fedora's next shell sources every file. Choices now live with
Sextant's own data, which no project folder can write. A pointer beside the
manuscript is still honoured when it names a folder inside the manuscript's
own, which is as far as a shipped one can safely reach.
"""

import json
from pathlib import Path

from sextant.safefs import write_file

#: Sidecar naming the library folder, written next to the manuscript.
POINTER = ".sextant-library"

DEFAULT_NAME = "refs"


def default_refs_for(manuscript: Path | str) -> Path:
    """Where the library would go if nobody says otherwise."""
    return Path(manuscript).resolve().parent / DEFAULT_NAME


def refs_for(manuscript: Path | str, registry: Path) -> Path:
    """The library folder for this manuscript, chosen or defaulted.

    `registry` is where Sextant keeps the choices made in it. Never creates
    anything. A caller that needs the folder to exist asks the user first:
    silently making directories in someone's project is how a file ends up
    somewhere they will not think to look.
    """
    manuscript = Path(manuscript).resolve()
    chosen = _choices(registry).get(str(manuscript))
    if chosen:
        return Path(chosen)
    return _pointer(manuscript) or default_refs_for(manuscript)


def set_refs_for(manuscript: Path | str, refs_dir: Path | str, registry: Path) -> Path:
    """Record `refs_dir` as this manuscript's library and return it."""
    manuscript = Path(manuscript).resolve()
    resolved = Path(refs_dir).expanduser().resolve()
    choices = _choices(registry)
    choices[str(manuscript)] = str(resolved)
    write_file(registry, json.dumps(choices, indent=2))
    return resolved


def _choices(registry: Path) -> dict[str, str]:
    try:
        choices = json.loads(Path(registry).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return choices if isinstance(choices, dict) else {}


def _pointer(manuscript: Path) -> Path | None:
    """The folder a .sextant-library beside `manuscript` names, if it is safe.

    Only one inside the manuscript's own folder, reached without leaving it
    through a link, and with no ~ to expand: anything further is a choice a
    shipped file has no business making.
    """
    folder = manuscript.parent
    pointer = folder / POINTER
    if pointer.is_symlink() or not pointer.is_file():
        return None
    try:
        named = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not named:
        return None
    target = (folder / named).resolve()
    return target if target.is_relative_to(folder.resolve()) else None
