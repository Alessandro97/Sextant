"""Read a `.env` file into the environment, without taking a dependency.

`.env.example` has always said the key is "read only by this app, never
exported to your shell" -- the point being that no other tool on the machine
inherits it. That only holds if this app does the reading, and until now
nothing did: the file was documented, created by readers, and ignored. The
error message then told them to create the file they had just created.

A real environment variable always wins over the file. `KEY=... sextant ask`
is an explicit instruction for one run, and a stale `.env` should not quietly
override it.
"""

import os
from pathlib import Path

#: Where to look when no path is given. Relative, so it follows the reader
#: from one project to the next rather than binding to an install location.
DEFAULT = Path(".env")

#: The only names taken from the file. A .env usually belongs to some other
#: project as well, and one beside a manuscript someone sent could otherwise
#: set LD_PRELOAD for every program this one starts, or ANTHROPIC_BASE_URL to
#: send the real key elsewhere.
NAMES = frozenset({"ANTHROPIC_API_KEY"})

#: Which of those came from the file, and so stay with this process.
_from_file: set[str] = set()


def parse_env(text: str) -> dict[str, str]:
    """The subset of the format that a key file needs, and nothing more.

    Comments, blank lines, optional `export`, and quotes around the value.
    No interpolation and no multi-line values: a secret does not need them,
    and every extra rule is another way to read a file wrongly.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def load_env(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Put `path` into os.environ and return what was actually set.

    A missing file is not an error: most runs do not need one, and the viewer
    needs none at all.
    """
    target = DEFAULT if path is None else Path(path)
    try:
        text = target.read_text()
    except OSError:
        return {}

    applied: dict[str, str] = {}
    for name, value in parse_env(text).items():
        if name not in NAMES:
            continue
        if override or name not in os.environ:
            os.environ[name] = value
            _from_file.add(name)
            applied[name] = value
    return applied


def child_env() -> dict[str, str]:
    """The environment for a program this one starts.

    Everything but what came from the file, which is the promise above. It
    matters for cost too: Claude Code handed a key in its environment uses it
    instead of the reader's own login.
    """
    return {k: v for k, v in os.environ.items() if k not in _from_file}
