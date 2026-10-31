"""Given what the user pointed at, find the compiled manuscript PDF.

Citation link annotations only exist in compiled output, so a .tex on its own
cannot drive the reader. Rather than degrade silently we locate the PDF or say
exactly what is missing.
"""

from pathlib import Path

import pymupdf

#: Never mistake a downloaded reference for the manuscript.
_EXCLUDED_DIRS = {"refs", "blobs", ".downloads", "inbox"}


class NoCompiledPdfError(Exception):
    """No compiled PDF with citation links could be found for this manuscript."""


def has_citation_markers(pdf_path: Path) -> bool:
    """Either hyperref links or superscript citation numbers."""
    if has_citation_links(pdf_path):
        return True
    from sextant.manuscript.superscript import superscript_markers

    try:
        return bool(superscript_markers(pdf_path))
    except Exception:  # noqa: BLE001 - an unreadable file is simply not one
        return False


def has_citation_links(pdf_path: Path) -> bool:
    try:
        doc = pymupdf.open(pdf_path)
    except Exception:
        return False
    try:
        for page in doc:
            for link in page.get_links():
                name = str(link.get("nameddest") or link.get("name") or "")
                if name.startswith("cite."):
                    return True
    finally:
        doc.close()
    return False


def compiled_pdf_for(target: Path | str) -> Path:
    """The compiled PDF for `target`, which may be a .pdf or a .tex."""
    target = Path(target).resolve()

    if target.suffix.lower() == ".pdf":
        return target

    root = target.parent
    candidates = [
        path
        for path in list(root.glob("*.pdf")) + list(root.glob("*/*.pdf"))
        if not _excluded(path, root)
    ]
    # Newest first: a rebuild should win over a stale copy.
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for candidate in candidates:
        if has_citation_links(candidate):
            return candidate

    raise NoCompiledPdfError(
        f"no compiled PDF with citation links found near {target.name}. "
        "Compile the manuscript (pdflatex/latexmk) so hyperref emits citation "
        "links, then point at the PDF directly."
    )


def _excluded(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part in _EXCLUDED_DIRS for part in relative.parts[:-1])
