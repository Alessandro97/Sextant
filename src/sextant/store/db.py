"""SQLite-backed store.

Externally-owned PDFs are recorded by absolute path and never moved, copied,
or modified. The store holds a reference plus a content hash so a file that
has moved or changed can be detected.
"""

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sextant.models import Page, Paper, Rect, Word

SCHEMA = Path(__file__).with_name("schema.sql")


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Store:
    def __init__(self, conn: sqlite3.Connection, db_path: Path) -> None:
        self._conn = conn
        self._db_path = db_path

    @property
    def blobs_dir(self) -> Path:
        """Content-addressed home for PDFs Sextant fetched itself.

        Distinct from externally-owned papers, which stay where the user put
        them and are only referenced. A fetched PDF has no other home, so the
        store owns it — and owning it once means a paper cited from three
        manuscripts is downloaded once.
        """
        return self._db_path.parent / "blobs"

    @classmethod
    def open(cls, db_path: Path | str) -> "Store":
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA.read_text())
        conn.commit()
        return cls(conn, db_path)

    def close(self) -> None:
        self._conn.close()

    def add_paper(self, pdf_path: Path | str, title: str | None = None) -> Paper:
        """Register a PDF. Idempotent on content hash."""
        pdf_path = Path(pdf_path).resolve()
        digest = content_hash(pdf_path)
        paper_id = digest[:16]

        self._conn.execute(
            """
            INSERT INTO papers (id, path, content_hash, title, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                path  = excluded.path,
                title = COALESCE(excluded.title, papers.title)
            """,
            (
                paper_id,
                str(pdf_path),
                digest,
                title,
                datetime.now(UTC).isoformat(),
            ),
        )
        self._conn.commit()
        found = self.get_paper(paper_id)
        assert found is not None
        return found

    def adopt_pdf(self, src: Path | str, title: str | None = None) -> Paper:
        """Copy a fetched PDF into the store and register it.

        The source is copied, never moved: a file staged in one manuscript's
        refs/ may still be wanted there, and destroying a caller's input is
        never this method's business. Idempotent on content — adopting the
        same bytes twice yields one blob and one row.
        """
        src = Path(src).resolve()
        digest = content_hash(src)
        blob = self.blobs_dir / f"{digest}.pdf"

        if not blob.exists():
            blob.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, blob)

        return self.add_paper(blob, title=title)

    def get_paper(self, paper_id: str) -> Paper | None:
        row = self._conn.execute(
            "SELECT * FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        return _row_to_paper(row) if row else None

    def list_papers(self) -> list[Paper]:
        rows = self._conn.execute("SELECT * FROM papers ORDER BY created_at").fetchall()
        return [_row_to_paper(row) for row in rows]

    def staleness(self, paper: Paper) -> str | None:
        """None if the file is unchanged, else 'missing' or 'changed'.

        Externally-owned PDFs live outside the store and can move or be edited
        under us. Callers check this before trusting a stored index.
        """
        path = Path(paper.path)
        if not path.exists():
            return "missing"
        if content_hash(path) != paper.content_hash:
            return "changed"
        return None

    def set_index_status(self, paper_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE papers SET index_status = ? WHERE id = ?", (status, paper_id)
        )
        self._conn.commit()

    def save_pages(self, paper_id: str, pages: list[Page]) -> None:
        """Replace the stored index for a paper."""
        self._conn.execute("DELETE FROM pages WHERE paper_id = ?", (paper_id,))
        self._conn.executemany(
            "INSERT INTO pages (paper_id, page_number, text, words) VALUES (?, ?, ?, ?)",
            [
                (paper_id, page.number, page.text, _dump_words(page.words))
                for page in pages
            ],
        )
        self._conn.commit()

    def load_pages(self, paper_id: str) -> list[Page]:
        rows = self._conn.execute(
            "SELECT page_number, text, words FROM pages "
            "WHERE paper_id = ? ORDER BY page_number",
            (paper_id,),
        ).fetchall()
        return [
            Page(
                number=row["page_number"],
                text=row["text"],
                words=_load_words(row["words"]),
            )
            for row in rows
        ]


def _row_to_paper(row: sqlite3.Row) -> Paper:
    return Paper(
        id=row["id"],
        path=row["path"],
        content_hash=row["content_hash"],
        title=row["title"],
        index_status=row["index_status"],
    )


def _dump_words(words: tuple[Word, ...]) -> str:
    return json.dumps(
        [[w.start, w.end, w.rect.x0, w.rect.y0, w.rect.x1, w.rect.y1] for w in words]
    )


def _load_words(blob: str) -> tuple[Word, ...]:
    return tuple(
        Word(start=int(s), end=int(e), rect=Rect(x0, y0, x1, y1))
        for s, e, x0, y0, x1, y1 in json.loads(blob)
    )
