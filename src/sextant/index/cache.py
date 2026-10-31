"""Extracted pages, remembered between requests.

Every marker click rebuilt the whole workspace, and the whole workspace
re-extracted every cited paper: measured at 912 pages across 17 documents, or
20 seconds, for one click on one citation.

Keyed by path, size and modification time, so a paper replaced on disk is
re-read and one that has not changed is not.
"""

from collections import OrderedDict
from pathlib import Path

from sextant.index.extract import extract_pages
from sextant.models import Page

#: Documents held at once. A 170-page specification is a few MB of text; a
#: manuscript's whole bibliography comfortably fits.
MAX_DOCUMENTS = 64

_cache: "OrderedDict[tuple, list[Page]]" = OrderedDict()


def _signature(path: Path) -> tuple:
    stat = path.stat()
    return (str(path), stat.st_size, stat.st_mtime_ns)


def cached_pages(pdf_path: Path | str) -> list[Page]:
    """extract_pages, but only once per version of a file.

    Errors are deliberately not cached: an unreadable file is usually being
    written, and the next request should try again rather than inherit a
    failure for the life of the process.
    """
    path = Path(pdf_path)
    try:
        key = _signature(path)
    except OSError:
        return extract_pages(path)

    hit = _cache.get(key)
    if hit is not None:
        _cache.move_to_end(key)
        return hit

    pages = extract_pages(path)
    _cache[key] = pages
    _cache.move_to_end(key)
    while len(_cache) > MAX_DOCUMENTS:
        _cache.popitem(last=False)
    return pages


def clear() -> None:
    _cache.clear()


def size() -> int:
    return len(_cache)
