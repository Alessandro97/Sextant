"""FastAPI app for the local viewer.

create_app takes an explicit store path rather than reading a global, so tests
run against a temporary library and never touch the user's real one.
"""

import hashlib
import json as jsonlib
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from sextant.audit.screen import excerpt_around, screen_all
from sextant.audit.report import to_json as audit_to_json
from sextant.audit.runner import audit_manuscript
from sextant.audit.sites import citation_sites_from_file
from sextant.ground.recover import recover_span
from sextant.index.cache import cached_pages
from sextant.index.find import find_all
from sextant.index.extract import (
    NoTextLayerError,
    UnreadablePdfError,
)
from sextant.models import Paper
from sextant.chat.assess import assess
from sextant.chat.compose import answer as compose_answer
from sextant.chat.compose import ask_cli
from sextant.chat import pending
from sextant.chat.compose import backends as chat_backends
from sextant.chat.retrieve import Excerpt, top_excerpts
from sextant.manuscript.discover import (
    NoCompiledPdfError,
    compiled_pdf_for,
    has_citation_links,
    has_citation_markers,
)
from sextant.manuscript import library
from sextant.manuscript.links import NoCitationLinksError
from sextant.manuscript.workspace import build_workspace
from sextant.refs.folder import key_pdf, refs_dir
from dataclasses import replace

from sextant.refs.convert import CONVERTIBLE, to_pdf
from sextant.refs.folder import materialize
from sextant.refs.models import Resolution
from sextant.refs.pipeline import (
    convert_dropped_documents,
    pending_conversions,
    convertible_files,
    attempted_keys,
    fetch_references,
    load_entries,
    record_attempts,
    rescan_folder,
    resolution_rows,
)
from sextant.safefs import UnsafePathError, real_dir, write_file
from sextant.store.db import Store, content_hash
from sextant.web.geometry import as_fractions, rect_as_fraction
from sextant.web.render import PageOutOfRange, page_count, page_png, page_size

STATIC = Path(__file__).parent / "static"

#: Above this, "high" falls back to excerpts however it was asked. A 375-page
#: specification is a quarter of a million tokens per citation, and there are
#: as many citations as there are markers.
WHOLE_PAPER_CHARS = 250_000

#: How much of a cited paper the model is given, per citation. Measured over a
#: real 34-paper library whose median paper is 46,000 characters:
#:
#:   low    ~4 windows,  1,700 chars   ~   425 tokens
#:   mid   ~10 windows, 12,000 chars   ~ 3,000 tokens
#:   high   the paper    46,000 chars  ~11,600 tokens
#:
#: Multiply by the number of citations: a manuscript with thirty of them costs
#: about 350,000 tokens to assess at "high" and 13,000 at "low". That is the
#: whole reason this is a choice and not a constant.
EFFORT = {
    "low":  {"limit": 4,  "window": 420,  "first_page": False, "whole": False},
    "mid":  {"limit": 10, "window": 1200, "first_page": True,  "whole": False},
    "high": {"limit": 10, "window": 1200, "first_page": True,  "whole": True},
}
DEFAULT_EFFORT = "mid"

#: How much of a quote Claude gives is located in the paper. Past this, the
#: quote is shown only as far as it was found.
QUOTE_LOCATED = 200

#: The names this machine answers to when bound to it.
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
#: Methods that change something, and so must come from the viewer's own page.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: A Host header as a browser sends one: a name, or an IPv6 address in
#: brackets, and a port. Anything else -- "evil.example@127.0.0.1" -- is
#: parsed differently by different readers, so it is not parsed at all.
_HOST = re.compile(r"(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::\d{1,5})?")


def _hostname(netloc: str) -> str:
    return (urlsplit(f"//{netloc}").hostname or "").lower()


def _refusal(request: Request, answers_to: frozenset[str]) -> str | None:
    """Why a request did not come from the viewer's own page, or None.

    The viewer reads any PDF by path, lists directories, writes uploads and
    spends tokens. Bound to 127.0.0.1 it is out of the network's reach, but
    not the browser's: any open tab can send it requests, and a site that
    rebinds its own name to 127.0.0.1 can read the answers as well.
    """
    host = request.headers.get("host", "")
    if not _HOST.fullmatch(host) or _hostname(host) not in answers_to:
        # DNS rebinding. The browser still sends the attacker's name.
        return f"not addressed to this machine: {host}"

    if request.url.path.startswith("/api/") and \
            request.headers.get("sec-fetch-site", "").lower() in ("cross-site", "same-site"):
        return "requested by another site"

    origin = request.headers.get("origin")
    if request.method not in SAFE_METHODS and origin is not None \
            and urlsplit(origin).netloc != host:
        # Browsers always send Origin across origins, and "null" from sandboxed
        # frames. No Origin at all is curl or a script, not a web page.
        return f"sent from another page: {origin}"
    return None


def _asset_version() -> str:
    """A short digest of the front-end files, recomputed per request.

    Cheap -- four small files -- and it means a running server always serves
    a URL that matches what is on disk, even while it is being edited.
    """
    digest = hashlib.sha256()
    for name in ("index.html", "app.js", "tour.js", "app.css"):
        try:
            digest.update((STATIC / name).read_bytes())
        except OSError:
            continue
    return digest.hexdigest()[:10]


def create_app(db_path: Path, api_key: str | None = None,
               host: str = "127.0.0.1") -> FastAPI:
    """`host` is the address being served on, which is one more name requests
    may be addressed to."""
    app = FastAPI(title="Sextant")
    # Library choices live with Sextant's own data, where no project folder
    # someone sent can write one.
    registry = Path(db_path).parent / "libraries.json"

    def refs_for(pdf: Path) -> Path:
        return library.refs_for(pdf, registry)

    def set_refs_for(pdf: Path, refs_dir: Path) -> Path:
        return library.set_refs_for(pdf, refs_dir, registry)
    # A bind address is bare, "::1" not "[::1]:8765", so it is not a netloc.
    answers_to = (LOOPBACK | {host.strip("[]").lower()}) - {""}

    @app.exception_handler(UnsafePathError)
    async def _refused_link(request: Request, exc: UnsafePathError):
        # A folder someone sent shipped a link where Sextant writes. Said as
        # a reason the reader can act on, not a 500.
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.middleware("http")
    async def _only_its_own_pages(request: Request, call_next):
        reason = _refusal(request, answers_to)
        if reason is not None:
            return JSONResponse({"detail": reason}, status_code=403)
        response = await call_next(request)
        # Never inside another site's page. Framed, the viewer's requests are
        # its own, and a page could steer clicks on Assess -- which spends.
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response

    def _paper_or_404(paper_id: str) -> Paper:
        store = Store.open(db_path)
        try:
            paper = store.get_paper(paper_id)
        finally:
            store.close()
        if paper is None:
            raise HTTPException(status_code=404, detail="no such paper")
        return paper

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/papers")
    def papers() -> dict:
        store = Store.open(db_path)
        try:
            return {
                "papers": [
                    {"id": p.id, "title": p.title or "(untitled)"}
                    for p in store.list_papers()
                ]
            }
        finally:
            store.close()

    @app.get("/api/papers/{paper_id}")
    def paper_detail(paper_id: str) -> dict:
        paper = _paper_or_404(paper_id)
        try:
            width, height = page_size(paper.path, 1)
            return {
                "id": paper.id,
                "title": paper.title or "(untitled)",
                "pages": page_count(paper.path),
                "width": width,
                "height": height,
            }
        except UnreadablePdfError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc

    @app.get("/api/papers/{paper_id}/page/{number}.png")
    def paper_page(paper_id: str, number: int, zoom: float = 1.5) -> Response:
        paper = _paper_or_404(paper_id)
        try:
            data = page_png(paper.path, number, zoom=zoom)
        except PageOutOfRange as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UnreadablePdfError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        return Response(content=data, media_type="image/png")

    @app.get("/api/papers/{paper_id}/locate")
    def locate_quote(paper_id: str, q: str) -> dict:
        """Find `q` in the paper and return the page plus overlay boxes.

        found=False is a real answer, not an error. The grounding invariant
        says we never paint a highlight we could not confirm, so the viewer
        must be able to say "that quote is not in this document".
        """
        if not q.strip():
            raise HTTPException(status_code=400, detail="empty query")

        paper = _paper_or_404(paper_id)
        try:
            pages = cached_pages(paper.path)
        except (UnreadablePdfError, NoTextLayerError) as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc

        span = recover_span(pages, 1, len(pages), q)
        if span is None:
            return {"found": False, "page": None, "boxes": [], "excerpt": ""}

        page = next(p for p in pages if p.number == span.page)
        width, height = page_size(paper.path, span.page)
        return {
            "found": True,
            "page": span.page,
            "boxes": as_fractions(span, width, height),
            "excerpt": page.text[
                max(0, span.char_start - 90) : span.char_end + 90
            ].strip(),
        }

    @app.get("/api/audit")
    def audit(tex: str) -> dict:
        manuscript = Path(tex)
        if not manuscript.exists():
            raise HTTPException(status_code=404, detail=f"cannot read {tex}")

        sites = citation_sites_from_file(manuscript)
        folder = refs_dir(manuscript)

        pdf_paths: dict[str, str] = {}
        for site in sites:
            for key in site.keys:
                candidate = key_pdf(folder, key)
                if key not in pdf_paths and candidate.exists():
                    pdf_paths[key] = str(candidate)

        payload = jsonlib.loads(audit_to_json(audit_manuscript(sites, pdf_paths)))

        # Attach each cited paper's store id so a finding is directly
        # clickable. Joining on content hash rather than title: titles are
        # noisy, frequently missing, and two papers can share one.
        store = Store.open(db_path)
        try:
            by_hash = {p.content_hash: p.id for p in store.list_papers()}
        finally:
            store.close()

        digests = {key: content_hash(Path(path)) for key, path in pdf_paths.items()}
        for finding in payload["findings"]:
            digest = digests.get(finding["key"])
            finding["paper_id"] = by_hash.get(digest) if digest else None

        return payload



    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)) -> dict:
        """Accept a manuscript PDF and give it a workspace of its own.

        The workspace is keyed by content hash, so uploading the same paper
        twice lands in the same folder and reuses the library already built
        there rather than downloading everything again.
        """
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="only PDF files are accepted")

        data = await file.read()
        if not data.startswith(b"%PDF"):
            raise HTTPException(status_code=415, detail="that file is not a PDF")

        digest = hashlib.sha256(data).hexdigest()[:16]
        folder = db_path.parent / "workspaces" / digest
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "paper.pdf"

        existed = target.exists()
        if not existed:
            write_file(target, data)

        if not has_citation_markers(target):
            if not existed:
                target.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail=(
                    "This PDF has no citation links. Sextant needs the compiled "
                    "output of a LaTeX manuscript built with hyperref, which is "
                    "what carries the [N] markers and their bibliography keys."
                ),
            )

        return {
            "path": str(target),
            "name": file.filename,
            "reused": existed,
            "library_exists": (folder / "refs").is_dir(),
        }


    class LibraryBody(BaseModel):
        path: str
        refs_dir: str | None = None
        create: bool = False

    @app.post("/api/workspace/library")
    def choose_library(body: LibraryBody) -> dict:
        """Say where this manuscript's reference library lives.

        Nothing is created without `create: true`. Making a directory in
        someone's project unasked is how a paper ends up somewhere they will
        not think to look, which has already happened twice here.
        """
        pdf = _resolve_manuscript(body.path)
        proposed = (
            Path(body.refs_dir).expanduser() if body.refs_dir else refs_for(pdf)
        )

        if not proposed.exists():
            if not body.create:
                return {
                    "refs_dir": str(proposed),
                    "exists": False,
                    "needs_confirmation": True,
                }
            try:
                # The folder itself first: a link to somewhere not yet made
                # reads as not there, and would have been followed to make it.
                real_dir(real_dir(proposed) / "inbox")
            except UnsafePathError:
                raise
            except OSError as exc:
                raise HTTPException(
                    status_code=400, detail=f"cannot create {proposed}: {exc}"
                ) from exc
        elif not proposed.is_dir():
            raise HTTPException(
                status_code=400, detail=f"{proposed} exists but is not a folder"
            )
        # Recorded resolved, so a link accepted here -- refs/ shipped pointing
        # at ~/.bashrc.d -- would be written into as though it were a folder.
        real_dir(proposed)

        chosen = set_refs_for(pdf, proposed)
        return {"refs_dir": str(chosen), "exists": True, "needs_confirmation": False}


    @app.get("/api/browse")
    def browse(dir: str | None = None) -> dict:
        """List folders and PDFs so a manuscript can be picked by its real path.

        A browser file picker hands over bytes and a filename and never a
        directory -- that is a security rule, not an oversight -- so choosing
        a file that way cannot tell Sextant where the manuscript lives, and
        the library ends up somewhere the user will not look. The server is
        already on the user's machine, so it can offer the one thing the
        browser cannot: a real path.

        Read-only, and the server binds to loopback.
        """
        here = Path(dir).expanduser() if dir else Path.home()
        try:
            here = here.resolve(strict=True)
        except (OSError, RuntimeError):
            raise HTTPException(status_code=404, detail=f"no such folder: {dir}") from None
        if not here.is_dir():
            here = here.parent

        folders, documents = [], []
        try:
            for entry in sorted(here.iterdir(), key=lambda p: p.name.lower()):
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    folders.append({"name": entry.name, "path": str(entry), "kind": "dir"})
                elif entry.suffix.lower() == ".pdf":
                    documents.append(
                        {"name": entry.name, "path": str(entry), "kind": "pdf"}
                    )
        except PermissionError:
            raise HTTPException(
                status_code=403, detail=f"cannot read {here}") from None

        return {
            "dir": str(here),
            "parent": str(here.parent) if here.parent != here else None,
            "entries": folders + documents,
        }

    # ---------------------------------------------------------------- workspace

    class WorkspaceBody(BaseModel):
        path: str
        #: Only meaningful for the assessment routes; harmless elsewhere.
        effort: str = DEFAULT_EFFORT

    class RescanBody(BaseModel):
        path: str
        #: Which documents to convert, by filename. Omitted means all of them,
        #: which is what "Update from folder" wants; the reader converting by
        #: hand picks a subset, because a 27 MB specification is tens of
        #: seconds and there is no reason to spend four of those to get one.
        convert: list[str] | None = None

    class FetchBody(BaseModel):
        path: str
        keys: list[str] = []
        offline: bool = False

    class ChatBody(BaseModel):
        path: str
        question: str
        key: str | None = None
        prefer: str | None = None

    def _resolve_manuscript(raw: str) -> Path:
        target = Path(raw).expanduser()
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"cannot read {raw}")
        try:
            return compiled_pdf_for(target)
        except NoCompiledPdfError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    workspaces: dict[str, tuple] = {}

    def _library_signature(pdf: Path) -> tuple:
        """Cheap fingerprint of everything a workspace is built from.

        Stat calls only. Changes when the manuscript changes, when a paper is
        added or removed, or when one is replaced -- which is exactly when the
        answer would differ.
        """
        out = refs_for(pdf)
        try:
            manuscript = (pdf.stat().st_size, pdf.stat().st_mtime_ns)
        except OSError:
            manuscript = (0, 0)
        papers = []
        if out.is_dir():
            for entry in sorted(out.iterdir()):
                try:
                    papers.append((entry.name, entry.stat().st_size,
                                   entry.stat().st_mtime_ns))
                except OSError:
                    continue
        return (str(out), manuscript, tuple(papers))

    def _workspace(pdf: Path):
        # Rebuilding this per request re-extracted every cited paper: measured
        # at 912 pages over 17 documents, 20 seconds, for one marker click.
        key = str(pdf)
        signature = _library_signature(pdf)
        cached = workspaces.get(key)
        if cached and cached[0] == signature:
            return cached[1]

        try:
            built = build_workspace(pdf, refs_for(pdf), db_path=db_path)
        except NoCitationLinksError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except UnreadablePdfError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc

        workspaces[key] = (signature, built)
        return built

    @app.post("/api/workspace")
    def open_workspace(body: WorkspaceBody) -> dict:
        """Open a manuscript: its markers, their status, and its own library."""
        pdf = _resolve_manuscript(body.path)
        ws = _workspace(pdf)

        markers = []
        for index, m in enumerate(ws.markers):
            width, height = ws.page_sizes[m.page - 1]
            markers.append({
                "id": index,
                "key": m.key,
                "marker": m.marker,
                "page": m.page,
                "box": rect_as_fraction(m.rect, width, height),
                "status": m.status,
                "claim": m.claim, "context": m.context,
                "quantity": (
                    {"value": m.quantity.value, "unit": m.quantity.unit}
                    if m.quantity else None
                ),
                "excerpt": m.excerpt,
                "reason": m.reason,
                "cited_page": m.span.page if m.span else None,
            })

        by_key = {r.key: r for r in ws.references}
        for marker in markers:
            reference = by_key.get(marker["key"])
            marker["paper_id"] = reference.paper_id if reference else None

        attempted = attempted_keys(refs_for(pdf))
        missing = [r.key for r in ws.references if not r.available]

        return {
            "pdf_path": ws.pdf_path,
            "pages": ws.pages,
            "missing": missing,
            # What auto-build should try. Empty once every reference has
            # actually been put to a resolver, so reopening a manuscript with
            # nothing left to try never touches the network.
            "unattempted": [k for k in missing if k not in attempted],
            "library_exists": (refs_for(pdf)).is_dir(),
            "refs_dir": str(refs_for(pdf)),
            "unconverted": [p.name for p in pending_conversions(refs_for(pdf))],
            "page_sizes": [{"width": w, "height": h} for w, h in ws.page_sizes],
            "counts": ws.counts(),
            "markers": markers,
            "references": [
                {
                    "key": r.key, "marker": r.marker, "cited_count": r.cited_count,
                    "available": r.available, "paper_id": r.paper_id, "pages": r.pages,
                    "title": r.title, "doi": r.doi, "raw": r.raw,
                }
                for r in ws.references
            ],
            "backends": chat_backends(),
        }

    @app.get("/api/workspace/page/{number}.png")
    def workspace_page(number: int, path: str, zoom: float = 1.6) -> Response:
        pdf = _resolve_manuscript(path)
        try:
            data = page_png(pdf, number, zoom=zoom)
        except PageOutOfRange as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UnreadablePdfError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        return Response(content=data, media_type="image/png")

    @app.post("/api/workspace/fetch")
    def workspace_fetch(body: FetchBody) -> dict:
        """Try to obtain the named references. Reports honestly per key."""
        pdf = _resolve_manuscript(body.path)
        entries = load_entries(pdf)

        # Default to what is missing, never to everything: re-resolving a
        # paper already sitting in refs/ is wasted network and can only
        # replace a good file with a worse one.
        wanted = body.keys or [
            r.key for r in _workspace(pdf).references if not r.available
        ]
        selected = [entries[k] for k in wanted if k in entries]
        unknown = [k for k in wanted if k not in entries]

        out = refs_for(pdf)
        store = Store.open(db_path)
        try:
            results = fetch_references(selected, store, out, offline=body.offline)
        finally:
            store.close()

        # Remember the keys that actually reached a resolver, so opening the
        # manuscript again does not re-attempt the ones that cannot resolve.
        #
        # Not the ones we merely wanted: a key absent from the bibliography
        # never reached a resolver at all, and recording it suppressed the
        # automatic fetch permanently. When the bibliography later parsed and
        # the key became resolvable, the reader still had to fetch by hand,
        # because a fetch that had never happened was on record as tried.
        # Nor the ones a source never answered for: a throttled arXiv says
        # nothing about the paper, and the next open should ask again.
        retry = {r.key for r in results if r.retry}
        record_attempts(out, [entry.key for entry in selected if entry.key not in retry])

        rows = resolution_rows(results)
        rows += [
            {
                "key": key, "status": "unresolved", "available": False,
                "reason": "not in any .bib file near the manuscript",
                "title": None, "doi": None, "resolver": None, "landing_pages": [],
            }
            for key in unknown
        ]
        return {"results": rows,
                "resolved": sum(1 for r in rows if r["available"])}


    @app.post("/api/workspace/rescan")
    def workspace_rescan(body: RescanBody) -> dict:
        """Look for papers the user added by hand and match them to references.

        This is the escape hatch for everything the resolvers cannot reach:
        paywalled articles, a standard sold or kept behind a login, a
        colleague's emailed preprint. Download it, drop it in the
        folder, press Update.
        """
        pdf = _resolve_manuscript(body.path)
        out = refs_for(pdf)
        ws = _workspace(pdf)
        entries = load_entries(pdf)

        pending = [
            Resolution(
                key=r.key,
                status="unresolved",
                reason="awaiting a manual copy",
                title=(entries[r.key].title if r.key in entries else None),
                doi=(entries[r.key].doi if r.key in entries else None),
            )
            for r in ws.references
            if not r.available
        ]

        converted = convert_dropped_documents(out, only=body.convert)
        adopted = _rescan_and_adopt(pdf, convert_only=body.convert)

        return {
            "converted": converted,
            "matched": [{"key": r.key, "title": r.title} for r in adopted],
            "still_missing": [
                r.key for r in ws.references
                if not r.available and r.key not in {a.key for a in adopted}
            ],
        }

    def _rescan_and_adopt(pdf: Path, convert_only=None) -> list:
        """Match anything in the refs folder to a reference and file it."""
        out = refs_for(pdf)
        ws = _workspace(pdf)
        entries = load_entries(pdf)

        pending = [
            Resolution(
                key=r.key,
                status="unresolved",
                reason="awaiting a manual copy",
                title=(entries[r.key].title if r.key in entries else None),
                doi=(entries[r.key].doi if r.key in entries else None),
            )
            for r in ws.references
            if not r.available
        ]
        matched = rescan_folder(out, pending, convert_only=convert_only)

        store = Store.open(db_path)
        try:
            adopted = []
            for resolution in matched:
                paper = store.adopt_pdf(resolution.pdf_path, title=resolution.title)
                adopted.append(replace(resolution, pdf_path=paper.path))
            if adopted:
                # Re-link the farm so refs/<key>.pdf points at the new papers.
                everything = adopted + [
                    Resolution(key=r.key, status="resolved", reason="",
                               pdf_path=str(key_pdf(out, r.key)))
                    for r in ws.references if r.available
                ]
                materialize(everything, out)
        finally:
            store.close()
        return adopted


    class AssessBody(BaseModel):
        path: str
        marker_id: int
        #: The author's case for the citation. Present means "judge again,
        #: with this in hand" -- so it bypasses the cached answer, which was
        #: reached without it.
        note: str = ""
        #: low | mid | high -- how much of the cited paper to hand the model.
        effort: str = DEFAULT_EFFORT
        #: Return a judgement only if one is already computed. The panel opens
        #: with this set, so displaying a marker never quietly starts a
        #: twenty-second model call the reader did not ask for.
        only_ready: bool = False

    def _mechanical_finding(marker) -> str:
        """What the figure check established, in a sentence for the prompt."""
        quantity = marker.quantity
        if marker.status == "verified" and quantity is not None:
            page = marker.span.page if marker.span else "?"
            return (
                f'The figure "{quantity.value} {quantity.unit}" from this '
                f"sentence was located on p. {page} of the cited paper. Whether "
                "it appears there for the reason this sentence gives is for you "
                "to judge."
            )
        if marker.status == "not-found" and quantity is not None:
            return (
                f'The figure "{quantity.value} {quantity.unit}" from this '
                "sentence does not appear anywhere in the cited paper."
            )
        return ""

    def _assess_marker(pdf: Path, marker_id: int, rebuttal: str = "",
                       effort: str = DEFAULT_EFFORT) -> dict:
        """Judge one citation. Shared by the on-demand route and the
        background pass that runs when a manuscript opens."""
        ws = _workspace(pdf)
        if marker_id < 0 or marker_id >= len(ws.markers):
            raise HTTPException(status_code=404, detail="no such marker")

        marker = ws.markers[marker_id]
        source = key_pdf(refs_for(pdf), marker.key)
        if not source.exists():
            raise HTTPException(
                status_code=404, detail=f"{marker.key} is not available locally"
            )

        try:
            pages = cached_pages(source)
        except (UnreadablePdfError, NoTextLayerError) as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc

        # A trimmed sentence can be too short to retrieve on: "Under these
        # conditions" pulled boilerplate from a long specification and earned the
        # cited paper an "unrelated" it did not deserve. Widen the query -- but
        # only the query; the sentence being judged is unchanged.
        query = marker.claim
        if len(query.split()) < 12 and marker.context:
            query = marker.context
        plan = EFFORT.get(effort, EFFORT[DEFAULT_EFFORT])
        excerpts = top_excerpts(query, pages, limit=4)
        wider = top_excerpts(query, pages, limit=plan["limit"],
                             window=plan["window"], first_page=plan["first_page"])

        # Judge from the whole paper when asked for and when it fits. Retrieval choosing what the
        # model may see meant a claim could be reported unsupported because the
        # sentence carrying it lost a keyword race -- an abstract saying "3
        # Mbps" never matched a manuscript saying "3 Mbit/s", so the one
        # passage that answered the citation was never shown. Claude can find
        # the correspondence itself; it only needs to be given the paper.
        #
        # The cap is for specifications, not papers: a 375-page standard
        # would be a quarter of a million tokens per citation. Those still go
        # through retrieval, which is why it is kept sharp.
        body = sum(len(p.text) for p in pages)
        whole = plan["whole"] and body <= WHOLE_PAPER_CHARS
        evidence = ([Excerpt(page=p.number, text=p.text, score=1.0)
                     for p in pages if p.text.strip()] if whole else wider)

        result = assess(
            marker.claim, evidence, ask=ask_cli, shown=excerpts, whole_paper=whole,
            title=pdf.stem.replace("_", " ")[:90],
            marker=marker.marker,
            context=marker.context,
            finding=_mechanical_finding(marker),
            rebuttal=rebuttal,
        )

        # Highlight what Claude actually pointed at, not the keyword window it
        # was shown. A quote is only used once located in the page layout --
        # the same rule the rest of Sextant follows.
        quoted: list[dict] = []
        for row in result.get("quotes", []):
            lo = row["page"] or 1
            span = recover_span(pages, lo, len(pages), row["text"][:QUOTE_LOCATED])
            if span is None:
                continue
            width, height = page_size(source, span.page)
            # The paper's own words for what was located, not the model's.
            # Only the first 200 characters are searched for, and the quote
            # past them is a claim nobody has checked.
            text = next(p.text for p in pages if p.number == span.page)
            shown = " ".join(text[span.char_start:span.char_end].split())
            if len(row["text"]) > QUOTE_LOCATED:
                shown += "…"     # cut where locating stopped, and saying so
            quoted.append({
                "page": span.page,
                "text": shown,
                "boxes": as_fractions(span, width, height),
            })
        result["quotes"] = quoted

        sizes: dict[int, tuple[float, float]] = {}
        for row, excerpt in zip(result["excerpts"], excerpts, strict=False):
            span = recover_span(pages, excerpt.page, excerpt.page, excerpt.text[:160])
            if span is None:
                row["boxes"] = []
                continue
            if span.page not in sizes:
                sizes[span.page] = page_size(source, span.page)
            width, height = sizes[span.page]
            row["page"] = span.page
            row["boxes"] = as_fractions(span, width, height)

        # Prefer Claude's own quote as the place to open at.
        best = (quoted[0] if quoted
                else (result["excerpts"][0] if result["excerpts"] else None))
        return {
            **result,
            "key": marker.key,
            "claim": marker.claim,
            "page": best["page"] if best else None,
            "boxes": best.get("boxes", []) if best else [],
            "paper_id": next(
                (r.paper_id for r in ws.references if r.key == marker.key), None
            ),
        }

    @app.post("/api/assess/all")
    def assess_everything(body: WorkspaceBody) -> dict:
        """Start judging every checkable citation, and return at once.

        A judgement is a model call of roughly twenty seconds. Waiting until
        the reader clicks means the reader waits; starting when the manuscript
        opens means they usually do not.
        """
        pdf = _resolve_manuscript(body.path)
        ws = _workspace(pdf)
        # Every citation, whatever the mechanical check said. A located
        # figure is not proof the paper supports the sentence -- a survey can
        # contain "21 GHz" in a passage unrelated to the claim citing it -- so
        # a verified marker is worth a judgement too.
        available = {r.key for r in ws.references if r.available}
        wanted = [i for i, m in enumerate(ws.markers) if m.key in available]
        return pending.run_in_background(
            str(pdf), wanted, lambda i: _assess_marker(pdf, i, effort=body.effort)
        )

    @app.post("/api/assess/reset")
    def assess_reset(body: WorkspaceBody) -> dict:
        """Throw away every judgement for this manuscript.

        Judgements are opinions, not measurements: the prompt changes, the
        retrieval changes, and a reader who has just improved a sentence wants
        it looked at afresh. Without this the only way to clear the cache was
        to restart the server.

        Discarding only. This used to start a fresh pass in the same breath,
        which spent the whole manuscript's budget on one click and could not
        be called back -- pressing it to clear a stale judgement committed you
        to paying for thirty new ones. Starting is a separate, priced button.
        """
        pdf = _resolve_manuscript(body.path)
        pending.forget(str(pdf))
        ws = _workspace(pdf)
        available = {r.key for r in ws.references if r.available}
        return {"done": 0, "running": False,
                "total": sum(1 for m in ws.markers if m.key in available)}

    @app.get("/api/assess/summary")
    def assess_summary(path: str) -> dict:
        """Scores so far, grouped by reference.

        A work cited nine times has nine judgements, and the list has room for
        one figure. The lowest is reported alongside the range: the reason to
        look at a reference is its weakest use, not its average.
        """
        pdf = _resolve_manuscript(path)
        ws = _workspace(pdf)

        by_key: dict[str, list[int]] = {}
        by_marker: dict[str, int] = {}
        # Which of these followed an argument from the reader. A score reached
        # after being argued for is not the same claim as one reached without,
        # and the list showed them identically.
        argued_keys: set[str] = set()
        argued_markers: dict[str, bool] = {}
        for index, marker in enumerate(ws.markers):
            ready = pending.get(str(pdf), index)
            if not ready:
                continue
            score = ready.get("score")
            if isinstance(score, int):
                by_key.setdefault(marker.key, []).append(score)
                # Per citation as well as per reference: a work cited nine
                # times has nine judgements, and the list of where it appears
                # is exactly where they differ.
                by_marker[str(index)] = score
                if ready.get("revised"):
                    argued_keys.add(marker.key)
                    argued_markers[str(index)] = True

        return {
            "scores": {
                key: {"low": min(v), "high": max(v), "n": len(v),
                      "revised": key in argued_keys}
                for key, v in by_key.items()
            },
            "by_marker": by_marker,
            "revised": argued_markers,
            **pending.progress(str(pdf)),
        }

    @app.get("/api/assess/progress")
    def assess_progress(path: str) -> dict:
        return pending.progress(str(_resolve_manuscript(path)))

    @app.post("/api/assess")
    def assess_marker(body: AssessBody) -> dict:
        """Is the cited paper relevant to the sentence citing it?

        For a citation with no quantity there is nothing to screen
        mechanically. Retrieval alone cannot answer it either -- measured, term
        overlap scores a claim the same against its own source as against a
        random paper from the same library. So the passages come back free and
        instantly as somewhere to look, and the judgement is a model call.
        """
        pdf = _resolve_manuscript(body.path)
        if body.note.strip():
            revised = _assess_marker(pdf, body.marker_id, rebuttal=body.note,
                                     effort=body.effort)
            revised["revised"] = True
            revised["note"] = body.note.strip()
            # Through revise(), not put(): the judgement being displaced is
            # what Revert puts back, and it is gone the moment it is
            # overwritten.
            pending.revise(str(pdf), body.marker_id, revised)
            return {**revised, "precomputed": False}

        ready = pending.get(str(pdf), body.marker_id)
        if ready is not None:
            return {**ready, "precomputed": True}
        if body.only_ready:
            return {"verdict": None, "precomputed": False, "excerpts": [],
                    "why": "", "pending": True}
        result = _assess_marker(pdf, body.marker_id, effort=body.effort)
        pending.put(str(pdf), body.marker_id, result)
        return {**result, "precomputed": False}

    class MarkerBody(BaseModel):
        path: str
        marker_id: int

    @app.post("/api/assess/revert")
    def assess_revert(body: MarkerBody) -> dict:
        """Discard a revision and put back the judgement it replaced.

        An argument is worth making and worth taking back. Until this, undoing
        one meant Re-assess, which throws away every judgement in the
        manuscript to correct a single citation.
        """
        pdf = _resolve_manuscript(body.path)
        restored = pending.revert(str(pdf), body.marker_id)
        if restored is None:
            raise HTTPException(
                status_code=404, detail="no earlier judgement to go back to"
            )
        return {**restored, "precomputed": True}

    @app.post("/api/marker/occurrences")
    def marker_occurrences(body: MarkerBody) -> dict:
        """Every place this citation's quantity appears in the cited paper.

        The verdict only needs to know whether it is there at all. A reader
        checking the citation wants the other answer -- where, everywhere --
        so they can judge whether the occurrence the tool picked is the one
        the sentence is actually about.

        Also lists the other markers citing the same reference, because a work
        cited nine times is nine separate claims and they are easiest to check
        one after another.
        """
        pdf = _resolve_manuscript(body.path)
        ws = _workspace(pdf)
        if body.marker_id < 0 or body.marker_id >= len(ws.markers):
            raise HTTPException(status_code=404, detail="no such marker")

        marker = ws.markers[body.marker_id]
        siblings = [
            {"id": i, "marker": m.marker, "page": m.page, "status": m.status,
             "claim": m.claim}
            for i, m in enumerate(ws.markers)
            if m.key == marker.key
        ]

        payload = {
            "key": marker.key,
            "siblings": siblings,
            "position": next(
                (n for n, s in enumerate(siblings) if s["id"] == body.marker_id), 0
            ),
            "highlights": {},
            "total": 0,
            "capped": False,
        }

        source = key_pdf(refs_for(pdf), marker.key)
        if marker.quantity is None or not source.exists():
            return payload

        try:
            pages = cached_pages(source)
        except (UnreadablePdfError, NoTextLayerError):
            return payload

        spans, total = screen_all(marker.quantity, pages)
        sizes: dict[int, tuple[float, float]] = {}
        highlights: dict[str, list] = {}
        for span in spans:
            if span.page not in sizes:
                sizes[span.page] = page_size(source, span.page)
            width, height = sizes[span.page]
            highlights.setdefault(str(span.page), []).extend(
                as_fractions(span, width, height)
            )

        by_number = {p.number: p for p in pages}
        payload["highlights"] = highlights
        payload["total"] = total
        payload["capped"] = total > len(spans)
        payload["occurrences"] = [
            {
                "page": s.page,
                "text": excerpt_around(
                    by_number[s.page].text, s.char_start, s.char_end, width=70
                ),
            }
            for s in spans
        ]
        return payload


    @app.post("/api/marker/passages")
    def marker_passages(body: MarkerBody) -> dict:
        """The closest passages in the cited paper, found without a model.

        Term overlap costs nothing and runs offline, so it can be done for
        every citation the moment a manuscript opens. What it produces is a
        place to look -- never a verdict. Measured on a real manuscript, a
        claim scores against its own cited paper (median 0.27) exactly as it
        scores against a random other paper from the same library (0.28), so
        the ranking cannot tell a real citation from a plausible substitute.
        It can still point at the page a reader should start on.

        Each passage is put through recover_span before it is returned, so a
        highlight is only drawn where the text was actually located -- the
        same rule the rest of Sextant follows.
        """
        pdf = _resolve_manuscript(body.path)
        ws = _workspace(pdf)
        if body.marker_id < 0 or body.marker_id >= len(ws.markers):
            raise HTTPException(status_code=404, detail="no such marker")

        marker = ws.markers[body.marker_id]
        source = key_pdf(refs_for(pdf), marker.key)
        empty = {"key": marker.key, "passages": [], "highlights": {}}
        if not source.exists():
            return empty

        try:
            pages = cached_pages(source)
        except (UnreadablePdfError, NoTextLayerError):
            return empty

        # A trimmed sentence is too short to retrieve on, exactly as in the
        # judged path.
        query = marker.claim
        if len(query.split()) < 12 and marker.context:
            query = marker.context

        found = top_excerpts(query, pages, limit=3, window=420, first_page=True)
        sizes: dict[int, tuple[float, float]] = {}
        highlights: dict[str, list] = {}
        passages = []
        for excerpt in found:
            span = recover_span(pages, excerpt.page, excerpt.page, excerpt.text[:160])
            boxes = []
            if span is not None:
                if span.page not in sizes:
                    sizes[span.page] = page_size(source, span.page)
                width, height = sizes[span.page]
                boxes = as_fractions(span, width, height)
                highlights.setdefault(str(span.page), []).extend(boxes)
            passages.append({"page": span.page if span else excerpt.page,
                             "text": excerpt.text, "boxes": boxes})

        return {"key": marker.key, "passages": passages, "highlights": highlights}

    @app.post("/api/workspace/add")
    async def add_reference_files(
        path: str = Form(...), files: list[UploadFile] = File(...)
    ) -> dict:
        """Take reference papers straight from the browser into the library.

        Until this existed the only way to add a paper was to find the refs
        folder in a file manager -- a content-hashed path under
        ~/.local/share that nobody would guess -- and copy the file there. The
        one file picker in the interface uploaded a manuscript, which is not
        what someone reaching for it wants when they have just downloaded a
        cited paper.

        Files land in refs/inbox/, are converted if they are office documents,
        and are matched to references by title and DOI. Nothing is renamed:
        the match is on content, so a publisher's filename is fine.
        """
        pdf = _resolve_manuscript(path)
        inbox = real_dir(real_dir(refs_for(pdf)) / "inbox")

        saved, rejected = [], []
        for upload in files:
            name = Path(upload.filename or "unnamed").name
            data = await upload.read()
            suffix = Path(name).suffix.lower()
            if suffix != ".pdf" and suffix not in CONVERTIBLE:
                rejected.append({"name": name, "reason": "not a PDF or office document"})
                continue
            if suffix == ".pdf" and not data.startswith(b"%PDF"):
                rejected.append({"name": name, "reason": "not actually a PDF"})
                continue
            write_file(inbox / name, data)
            saved.append(name)

        # Only what was just added. Sweeping the folder here converted every
        # office document sitting in it -- add one PDF, wait out four 27 MB
        # specifications you did not ask about.
        converted = convert_dropped_documents(refs_for(pdf), only=saved)
        matched = _rescan_and_adopt(pdf, convert_only=saved)

        return {
            "saved": saved,
            "rejected": rejected,
            "converted": [c for c in converted if c["pdf"]],
            "matched": [{"key": r.key, "title": r.title} for r in matched],
            "unmatched": [
                n for n in saved
                if not any(m.key for m in matched)
            ] if not matched else [],
        }


    @app.post("/api/workspace/assign")
    async def assign_reference_file(
        path: str = Form(...), key: str = Form(...), file: UploadFile = File(...)
    ) -> dict:
        """File this exact document under this exact reference.

        Title matching is a convenience and it will sometimes be wrong -- a
        standard whose release differs, a preprint whose title was changed
        before publication, a scan with no text layer. When the reader already
        knows which paper this is, asking them to make the matcher agree is
        pointless. This bypasses it entirely.
        """
        pdf = _resolve_manuscript(path)
        out = refs_for(pdf)
        ws = _workspace(pdf)
        if key not in {r.key for r in ws.references}:
            raise HTTPException(status_code=404, detail=f"{key} is not cited here")

        name = Path(file.filename or "chosen").name
        suffix = Path(name).suffix.lower()
        if suffix != ".pdf" and suffix not in CONVERTIBLE:
            raise HTTPException(
                status_code=415, detail="only PDFs and office documents")

        data = await file.read()
        if suffix == ".pdf" and not data.startswith(b"%PDF"):
            raise HTTPException(status_code=415, detail="that file is not a PDF")

        staging = real_dir(real_dir(out) / "inbox")
        dropped = staging / name
        write_file(dropped, data)

        if suffix != ".pdf":
            try:
                dropped = to_pdf(dropped, staging)
            except Exception as exc:  # noqa: BLE001 - reported to the reader
                raise HTTPException(
                    status_code=400, detail=f"could not convert: {exc}") from exc

        store = Store.open(db_path)
        try:
            paper = store.adopt_pdf(dropped, title=next(
                (r.title for r in ws.references if r.key == key), None))
            keep = [
                Resolution(key=r.key, status="resolved", reason="",
                           pdf_path=str(key_pdf(out, r.key)))
                for r in ws.references if r.available and r.key != key
            ]
            materialize(
                [Resolution(key=key, status="resolved", reason="assigned by hand",
                            pdf_path=paper.path, resolver="manual")] + keep,
                out,
            )
        finally:
            store.close()

        return {"key": key, "filed": name, "pages": page_count(paper.path)}


    def _find_in(pdf: Path, query: str) -> dict:
        """Locate `query` in a document and give the browser somewhere to paint."""
        try:
            pages = cached_pages(pdf)
        except (UnreadablePdfError, NoTextLayerError) as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc

        hits, total = find_all(pages, query)
        sizes: dict[int, tuple[float, float]] = {}
        rows = []
        for hit in hits:
            if hit.span.page not in sizes:
                sizes[hit.span.page] = page_size(pdf, hit.span.page)
            width, height = sizes[hit.span.page]
            rows.append({
                "page": hit.span.page,
                "text": hit.text,
                "boxes": as_fractions(hit.span, width, height),
            })
        return {"hits": rows, "total": total, "shown": len(rows)}

    @app.get("/api/workspace/find")
    def find_in_manuscript(path: str, q: str) -> dict:
        return _find_in(_resolve_manuscript(path), q)

    @app.get("/api/papers/{paper_id}/find")
    def find_in_paper(paper_id: str, q: str) -> dict:
        return _find_in(Path(_paper_or_404(paper_id).path), q)

    # --------------------------------------------------------------------- chat

    @app.get("/api/backends")
    def backends() -> dict:
        return chat_backends()

    @app.post("/api/chat")
    def chat(body: ChatBody) -> dict:
        """Ask about the manuscript, or about one of its references."""
        pdf = _resolve_manuscript(body.path)

        if body.key:
            target = key_pdf(refs_for(pdf), body.key)
            title = body.key
            if not target.exists():
                raise HTTPException(
                    status_code=404, detail=f"{body.key} is not available locally"
                )
        else:
            target, title = pdf, pdf.stem

        try:
            pages = cached_pages(target)
        except (UnreadablePdfError, NoTextLayerError) as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc

        excerpts = top_excerpts(body.question, pages, limit=5)
        result = compose_answer(
            body.question, title, excerpts,
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            prefer=body.prefer,
        )
        return {**result, "target": title}

    @app.get("/")
    def index() -> Response:
        """The page, with its asset URLs stamped by content.

        Eight times in one session a change appeared not to work because the
        browser had the previous app.js. A cached stylesheet or script is
        indistinguishable from a broken feature, so the version is baked into
        the URL and the page itself is never stored.
        """
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        html = html.replace("/static/app.css", f"/static/app.css?v={_asset_version()}")
        html = html.replace("/static/app.js", f"/static/app.js?v={_asset_version()}")
        html = html.replace("/static/tour.js", f"/static/tour.js?v={_asset_version()}")
        return Response(
            content=html,
            media_type="text/html",
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
