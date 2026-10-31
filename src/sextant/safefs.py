"""Writing inside a folder someone else made.

A manuscript folder arrives as a clone, a zip or a tarball, and all three keep
symbolic links. One shipping refs/MISSING.md as a link to ~/.bashrc had the
report written into the shell's startup file, titles and all, and the next
shell ran them. So nothing Sextant writes in a project folder goes through a
link: a link where a file belongs is replaced, and a folder that is a link is
refused.
"""

import os
import tempfile
from pathlib import Path


#: Read once, at import: setting the umask to read it is process-wide, and the
#: viewer writes from several threads.
_UMASK = os.umask(0)
os.umask(_UMASK)


class UnsafePathError(OSError):
    """Sextant would have written through a link it did not make."""


def real_dir(path: Path | str) -> Path:
    """`path` as a folder of its own, made if missing, never a link."""
    path = Path(path)
    if path.is_symlink():
        raise UnsafePathError(
            f"{path} is a symbolic link, and Sextant does not write through "
            "one. Choose the folder it points at instead.")
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_file(path: Path | str, data: bytes | str) -> None:
    """Put `data` at `path`, replacing whatever is there -- a link included.

    Written beside it and renamed into place: a rename replaces a link itself,
    where an ordinary write goes wherever the link points.
    """
    path = Path(path)
    real_dir(path.parent)
    if isinstance(data, str):
        data = data.encode("utf-8")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        # A temporary file is private. Given what a plain write would give it
        # instead, so a folder shared with co-authors stays readable to them.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o666 & ~_UMASK)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
