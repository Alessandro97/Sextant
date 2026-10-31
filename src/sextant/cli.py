"""Command-line surface. Every command supports --json for machine consumption."""

import json as jsonlib
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated

import typer

from sextant.audit.report import to_json as audit_json
from sextant.audit.report import to_markdown as audit_markdown
from sextant.audit.runner import audit_manuscript
from sextant.audit.sites import citation_sites_from_file
from sextant.dotenv import load_env
from sextant.ground.client import MissingCredentialsError, build_client
from sextant.ground.ground import GroundingError, ground
from sextant.ground.recover import recover_span
from sextant.index.extract import (
    NoTextLayerError,
    UnreadablePdfError,
    extract_pages,
)
from sextant.refs.bibtex import parse_bib
from sextant.refs.cache import CachingFetcher
from sextant.refs.folder import downloads_dir, key_pdf, materialize, refs_dir
from sextant.refs.http import FakeFetcher, HttpFetcher
from sextant.refs.inbox import adopt
from sextant.refs.latex import cited_keys_from_file
from sextant.refs.linkcheck import check_entry
from sextant.refs.pipeline import fetch_references, resolution_rows
from sextant.refs.resolvers import resolve_chain
from sextant.refs.resolvers.arxiv import ArxivResolver
from sextant.refs.resolvers.local import LocalResolver
from sextant.refs.resolvers.openalex import OpenAlexResolver
from sextant.refs.resolvers.threegpp import ThreeGppResolver
from sextant.refs.resolvers.unpaywall import UnpaywallResolver
from sextant.safefs import UnsafePathError, write_file
from sextant.store.db import Store

app = typer.Typer(help="Grounded research over a local paper library.")


@app.callback()
def _before_any_command() -> None:
    """Read .env before a command runs, so a key kept there is found.

    Here rather than at import: importing sextant should not reach for files
    in whatever directory the reader happens to be in, and the test suite
    imports these modules constantly.
    """
    load_env()

DEFAULT_DB = Path.home() / ".local" / "share" / "sextant" / "papers.db"

DbOption = Annotated[Path, typer.Option("--db", help="Path to the store database.")]
JsonOption = Annotated[bool, typer.Option("--json", help="Emit JSON.")]


def _emit(payload: dict, as_json: bool, human: str) -> None:
    typer.echo(jsonlib.dumps(payload, indent=2) if as_json else human)


@app.command()
def index(
    pdf: Path,
    db: DbOption = DEFAULT_DB,
    json: JsonOption = False,
) -> None:
    """Extract and store the span index for one PDF."""
    store = Store.open(db)
    try:
        try:
            paper = store.add_paper(pdf)
        except OSError as exc:
            # Missing path, unreadable permissions. Hashing the file happens
            # before anything else, so this is the first thing a typo'd path
            # hits.
            typer.echo(f"cannot read {pdf}: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        try:
            pages = extract_pages(pdf)
        except UnreadablePdfError as exc:
            store.set_index_status(paper.id, "unreadable")
            _emit(
                {"paper_id": paper.id, "index_status": "unreadable", "pages": 0},
                json,
                f"{pdf.name}: {exc}",
            )
            raise typer.Exit(code=1) from exc
        except NoTextLayerError:
            store.set_index_status(paper.id, "no-text-layer")
            _emit(
                {"paper_id": paper.id, "index_status": "no-text-layer", "pages": 0},
                json,
                f"{pdf.name}: no text layer — cannot index",
            )
            raise typer.Exit(code=1)

        store.save_pages(paper.id, pages)
        store.set_index_status(paper.id, "ok")
        _emit(
            {"paper_id": paper.id, "index_status": "ok", "pages": len(pages)},
            json,
            f"{pdf.name}: indexed {len(pages)} pages as {paper.id}",
        )
    finally:
        store.close()


@app.command()
def locate(
    paper_id: str,
    text: str,
    db: DbOption = DEFAULT_DB,
    json: JsonOption = False,
) -> None:
    """Find a passage in an indexed paper and print its span."""
    store = Store.open(db)
    try:
        pages = store.load_pages(paper_id)
        if not pages:
            typer.echo(f"no indexed pages for {paper_id}", err=True)
            raise typer.Exit(code=1)

        span = recover_span(pages, 1, len(pages), text)
        if span is None:
            typer.echo("not found in document", err=True)
            raise typer.Exit(code=1)

        _emit(
            {
                "page": span.page,
                "char_start": span.char_start,
                "char_end": span.char_end,
                "rects": [asdict(r) for r in span.rects],
            },
            json,
            f"page {span.page}, chars {span.char_start}-{span.char_end}, "
            f"{len(span.rects)} rects",
        )
    finally:
        store.close()


@app.command()
def ask(
    question: str,
    paper: Annotated[str, typer.Option("--paper", help="Paper id to ask about.")],
    db: DbOption = DEFAULT_DB,
    json: JsonOption = False,
) -> None:
    """Ask a question about an indexed paper. Every claim carries a verified span."""
    try:
        client = build_client()
    except MissingCredentialsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    store = Store.open(db)
    try:
        record = store.get_paper(paper)
        if record is None:
            typer.echo(f"unknown paper {paper}", err=True)
            raise typer.Exit(code=1)

        pages = store.load_pages(paper)
        if not pages:
            typer.echo(
                f"paper {paper} is not indexed — run `sextant index` first", err=True
            )
            raise typer.Exit(code=1)

        try:
            answer = ground(client, record, pages, question)
        except GroundingError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        if json:
            typer.echo(
                jsonlib.dumps(
                    {
                        "text": answer.text,
                        "evidence": [
                            {"cited_text": e.cited_text, "span": asdict(e.span)}
                            for e in answer.evidence
                        ],
                        "unverified": [asdict(u) for u in answer.unverified],
                    },
                    indent=2,
                )
            )
        else:
            typer.echo(answer.text)
            for item in answer.evidence:
                typer.echo(f"  [p.{item.span.page}] {item.cited_text}")
            for item in answer.unverified:
                typer.echo(
                    f"  [UNVERIFIED p.{item.start_page}] {item.cited_text}", err=True
                )
    finally:
        store.close()


OfflineOption = Annotated[
    bool, typer.Option("--offline", help="Skip all network resolvers (for testing).")
]


def _load_manuscript(tex: Path) -> tuple[set[str], dict]:
    """Cited keys plus the entries for those keys only.

    Exits with a clean message rather than a traceback: this is the first
    thing a typo'd path or a missing bibliography hits.
    """
    if not tex.is_file():
        typer.echo(f"cannot read {tex}", err=True)
        raise typer.Exit(code=1)

    keys = cited_keys_from_file(tex)

    entries: dict = {}
    for bib in sorted(tex.resolve().parent.rglob("*.bib")):
        entries.update(parse_bib(bib.read_text(errors="ignore")))

    if not entries:
        typer.echo(f"no .bib file found near {tex}", err=True)
        raise typer.Exit(code=1)

    return keys, {k: entries[k] for k in keys if k in entries}


@app.command()
def fetch(
    manuscript: Path,
    db: DbOption = DEFAULT_DB,
    offline: OfflineOption = False,
    json: JsonOption = False,
) -> None:
    """Resolve every cited reference and file it under refs/."""
    keys, entries = _load_manuscript(manuscript)

    store = Store.open(db)
    out = refs_dir(manuscript)
    try:
        results = fetch_references(entries.values(), store, out, offline=offline)

        resolved = sum(1 for r in results if r.pdf_path)
        sources = Counter(r.resolver for r in results if r.pdf_path)
        retry = sum(1 for r in results if r.retry and not r.pdf_path)
        _emit(
            {
                "cited_keys": len(keys),
                "in_bib": len(entries),
                "resolved": resolved,
                "missing": len(results) - resolved,
                "by_source": dict(sources),
                "retry": retry,
                "refs_dir": str(out),
                "results": resolution_rows(results),
            },
            json,
            f"{resolved}/{len(entries)} resolved -> {out}\n"
            + (f"  from: {', '.join(f'{n} {s}' for s, n in sources.most_common())}\n"
               if sources else "")
            + (f"  {retry} could not be asked this time; run fetch again later\n"
               if retry else "")
            + f"see {out / 'MISSING.md'} for the rest",
        )
    finally:
        store.close()


@app.command()
def linkcheck(
    manuscript: Path,
    offline: OfflineOption = False,
    json: JsonOption = False,
) -> None:
    """Check each cited entry's DOI actually resolves to that paper."""
    _, entries = _load_manuscript(manuscript)
    fetcher = FakeFetcher() if offline else HttpFetcher()

    checks = [check_entry(entry, fetcher) for entry in entries.values()]
    mismatches = [c for c in checks if c.verdict == "mismatch"]

    if json:
        typer.echo(
            jsonlib.dumps(
                {
                    "checks": [
                        {"key": c.key, "verdict": c.verdict,
                         "claimed": c.claimed, "actual": c.actual}
                        for c in checks
                    ],
                    "mismatches": len(mismatches),
                },
                indent=2,
            )
        )
    else:
        for c in mismatches:
            typer.echo(f"MISMATCH {c.key}\n  .bib : {c.claimed}\n  DOI  : {c.actual}")
        typer.echo(f"{len(checks)} checked, {len(mismatches)} mismatched")


@app.command()
def audit(
    manuscript: Path,
    refs: Annotated[
        Path | None,
        typer.Option("--refs", help="Folder of cited PDFs. Default: <manuscript dir>/refs."),
    ] = None,
    json: JsonOption = False,
) -> None:
    """Check each citation's claimed quantities against the cited paper.

    A `located` verdict means the quantity is present in the source, not that
    the source backs the claim. Read the excerpt and judge.
    """
    if not manuscript.exists():
        typer.echo(f"cannot read {manuscript}")
        raise typer.Exit(1)

    sites = citation_sites_from_file(manuscript)
    folder = refs or refs_dir(manuscript)

    pdf_paths: dict[str, str] = {}
    for site in sites:
        for key in site.keys:
            if key in pdf_paths:
                continue
            candidate = key_pdf(folder, key)
            if candidate.exists():
                pdf_paths[key] = str(candidate)

    report = audit_manuscript(sites, pdf_paths)

    if folder.is_dir():
        try:
            write_file(folder / "AUDIT.md", audit_markdown(report))
        except UnsafePathError as exc:
            typer.echo(f"not writing AUDIT.md: {exc}", err=True)

    if json:
        typer.echo(audit_json(report))
        return

    typer.echo(audit_markdown(report))
    if folder.is_dir():
        typer.echo(f"\nWritten to {folder / 'AUDIT.md'}")

    absent = report.counts().get("not-found", 0)
    if absent:
        typer.echo(
            f"\n{absent} citation(s) name a quantity the cited paper does not contain."
        )


@app.command()
def serve(
    db: DbOption = DEFAULT_DB,
    host: Annotated[str, typer.Option(
        "--host", help="Bind address. Requests must be addressed to this name.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8765,
    check: Annotated[
        bool, typer.Option("--check", help="Build the app and exit without serving.")
    ] = False,
) -> None:
    """Open the local viewer.

    Binds to 127.0.0.1. The library can hold unpublished manuscripts and
    paywalled PDFs, so it is not put on the network unless explicitly asked.
    """
    import uvicorn

    from sextant.web.app import LOOPBACK, create_app

    # Requests must be addressed to the name served on, and a wildcard is no
    # name a request ever carries: every one was refused, while the warning
    # below said the viewer was open to anyone who could reach it.
    if host.strip("[]") in ("0.0.0.0", "::", ""):
        typer.echo(
            f"--host {host} listens on every address, and Sextant only answers "
            "requests addressed to the one it serves on. Give this machine's "
            "own address on the network instead, such as 192.168.1.5.",
            err=True,
        )
        raise typer.Exit(code=2)

    application = create_app(db_path=db, host=host)

    if host.strip("[]").lower() not in LOOPBACK:
        typer.echo(
            f"Serving on {host}: there is no login, so anyone who can reach it "
            "can read every PDF on this machine.",
            err=True,
        )

    if check:
        typer.echo("ok")
        return

    typer.echo(f"Sextant viewer on http://{host}:{port}")
    uvicorn.run(application, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
