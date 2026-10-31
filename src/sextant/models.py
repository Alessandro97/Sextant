"""Core value types. All frozen — nothing downstream mutates a Span."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rect:
    """A rectangle in PyMuPDF page space. Origin is top-left, y grows downward.

    Note this is NOT PDF user space as defined by ISO 32000, which has a
    bottom-left origin with y increasing upward. PyMuPDF reports the flipped
    convention, and that is what get_text("words") returns.
    """

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True, slots=True)
class Word:
    """One word, with its character range in the owning Page.text."""

    start: int
    end: int
    rect: Rect


@dataclass(frozen=True, slots=True)
class Page:
    """A page's canonical text plus the words that produced it.

    `text` is built by this project (space-joined words), not taken from
    PyMuPDF's get_text(). That keeps the offset mapping exact and under our
    control.
    """

    number: int  # 1-indexed, matching the Anthropic citations API
    text: str
    words: tuple[Word, ...]


@dataclass(frozen=True, slots=True)
class Span:
    """A located, highlightable region of one page."""

    page: int
    char_start: int
    char_end: int
    rects: tuple[Rect, ...]


@dataclass(frozen=True, slots=True)
class Evidence:
    """A model citation that was verified against the local text layer."""

    cited_text: str
    span: Span


@dataclass(frozen=True, slots=True)
class Unverified:
    """A model citation that could NOT be located in the document.

    Keeps the page range the model claimed alongside the quote. That is the
    primary diagnostic for span recovery: a failure at the claimed page means
    normalization or extraction missed, while a quote that exists on a
    different page means the model misreported the location. Discarding the
    range collapses those two very different bugs into one opaque string.
    """

    cited_text: str
    start_page: int
    end_page: int


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """Answer text plus verified evidence.

    `unverified` holds citations the model returned that could NOT be located
    in the document. They are surfaced, never silently dropped, and never
    rendered as highlights.
    """

    text: str
    evidence: tuple[Evidence, ...]
    unverified: tuple[Unverified, ...]


@dataclass(frozen=True, slots=True)
class Paper:
    """A registered PDF and its indexing state.

    `title` and `index_status` are populated by the store as the paper is
    resolved and indexed, not at construction. `created_at` is deliberately
    store-internal and has no field here.
    """

    id: str
    path: str
    content_hash: str
    title: str | None = None
    index_status: str | None = None
