import os
from pathlib import Path

import pymupdf
import pytest

PAGE_ONE = [
    "III. CLUSTER THROUGHPUT",
    "Assuming a 5 ms commit interval and the shard",
    "configuration of Table II, the achievable aggregate",
    "write throughput is approximately 3 Mbit/s, which is",
    "shared across all active clients in the cluster.",
]

PAGE_TWO = [
    "IV. CLIENT LATENCY",
    "Cold caches at -31 dB/K remain the dominant",
    "limitation for clients served from the edge",
    "regions considered here.",
]


@pytest.fixture(autouse=True)
def _no_reader_credentials(monkeypatch):
    """A reader's own OpenAlex key or contact address must not change what
    the suite asks for."""
    import sextant.refs.resolvers.crossref as crossref
    import sextant.refs.resolvers.openalex as openalex
    import sextant.refs.resolvers.pmc as pmc
    import sextant.refs.resolvers.unpaywall as unpaywall

    monkeypatch.setattr(openalex, "KEY", "")
    monkeypatch.setattr(unpaywall, "CONTACT", "")
    monkeypatch.setattr(crossref, "CONTACT", "")
    monkeypatch.setattr(pmc, "CONTACT", "")


@pytest.fixture(autouse=True)
def _no_key_remembered_from_another_test(monkeypatch):
    """sextant.dotenv remembers which names it read from a file, for the life
    of the process. One test's .env must not decide what the next one hands
    to a child process."""
    import sextant.dotenv

    monkeypatch.setattr(sextant.dotenv, "_from_file", set())


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A real two-page PDF with known text. Deterministic across runs."""
    doc = pymupdf.open()
    for lines in (PAGE_ONE, PAGE_TWO):
        page = doc.new_page()
        y = 100.0
        for line in lines:
            page.insert_text((72.0, y), line, fontsize=11)
            y += 18.0
    path = tmp_path / "sample.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def blank_pdf(tmp_path: Path) -> Path:
    """A PDF with no text layer — a page containing only a drawn rectangle."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(72, 72, 300, 300), color=(0, 0, 0))
    path = tmp_path / "blank.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def latex_like_manuscript():
    """Builds a compiled-LaTeX-shaped paper at a given path.

    Shared because two separate defects live in this shape: the library showed
    opaque keys, and the fetch route selected no entries at all.
    """
    def _build(path):
        """A compiled LaTeX paper: hyperref keys on the markers, a printed
        reference list numbered [1]..[6]. This is the shape that showed a library
        of opaque keys -- the two are keyed differently and never met."""
        import pymupdf

        keys = ["4821377", "lopez2022survey", "okafor2021dynamics",
                "berg2005pasture", "4821391", "10051234"]
        doc = pymupdf.open()
        page = doc.new_page()
        y = 90.0
        for n, key in enumerate(keys, 1):
            sentence = f"Grazing impacts are discussed at length "
            page.insert_text((60.0, y), f"{sentence}[{n}].", fontsize=10)
            width = pymupdf.get_text_length(sentence, fontsize=10)
            label = pymupdf.get_text_length(f"[{n}]", fontsize=10)
            page.insert_link({"kind": pymupdf.LINK_NAMED,
                              "from": pymupdf.Rect(60.0 + width, y - 8, 60.0 + width + label, y + 2),
                              "name": f"cite.{key}"})
            y += 22.0

        refs = doc.new_page()
        refs.insert_text((60.0, 70.0), "References", fontsize=12)
        y = 100.0
        for n in range(1, 7):
            refs.insert_text(
                (60.0, y),
                f"[{n}] Author A{n}, Author B{n}. A paper about grazing number {n}. "
                f"Journal of Field Studies. 202{n % 10}. doi:10.5555/EXAMPLE.{n}",
                fontsize=8)
            y += 20.0
        doc.save(path); doc.close()
        return path

    return _build


# Real documents, supplied by whoever is running the suite.
#
# A hand-written bibliography and a typeset manuscript exercise things no
# generated fixture reaches -- a 400-entry .bib, a publisher's reference list,
# hyperref links laid down by a real LaTeX run. They cannot be committed, and
# pointing at one person's filesystem told everybody reading the repo what
# that person was writing. Each is a path in the environment, and every test
# that wants one is skipped when it is unset.
REAL_BIB = Path(os.environ["SEXTANT_TEST_BIB"]) if os.environ.get("SEXTANT_TEST_BIB") else None
REAL_TEX = Path(os.environ["SEXTANT_TEST_TEX"]) if os.environ.get("SEXTANT_TEST_TEX") else None
REAL_MANUSCRIPT_PDF = (
    Path(os.environ["SEXTANT_TEST_PAPER"]) if os.environ.get("SEXTANT_TEST_PAPER") else None
)


def _real(path: Path | None, variable: str) -> Path:
    if path is None:
        pytest.skip(f"set {variable} to run this")
    if not path.exists():
        pytest.skip(f"{variable} points at nothing: {path}")
    return path


@pytest.fixture
def real_bib_text() -> str:
    """A hand-maintained bibliography, whatever size the reader's own is."""
    return _real(REAL_BIB, "SEXTANT_TEST_BIB").read_text(errors="ignore")


@pytest.fixture
def real_tex_text() -> str:
    return _real(REAL_TEX, "SEXTANT_TEST_TEX").read_text(errors="ignore")


@pytest.fixture
def real_manuscript_pdf() -> Path:
    """A compiled manuscript carrying hyperref citation links."""
    return _real(REAL_MANUSCRIPT_PDF, "SEXTANT_TEST_PAPER")
