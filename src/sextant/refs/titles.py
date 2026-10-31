"""Decide whether two title strings name the same work.

Deliberately separate from sextant.index.normalize. That function backs the
offset map behind the grounding invariant, so it must be conservative and
reversible. This one is lossy and aggressive: it throws away everything that
does not help identify a paper.
"""

import html
import re
import unicodedata
from functools import lru_cache

MIN_COMPARABLE = 12  # characters; below this a prefix match means nothing
#: Words a main title needs before a subtitle may be dropped from it.
#: "Organic Chemistry" is the main title of a textbook and of any number of
#: papers.
MAIN_TITLE_WORDS = 4


#: A hyphen that a line break split, e.g. "Inte- grating" or
#: "producer- to-consumer". Requires word characters on both sides, so a dash
#: used as punctuation ("Wetlands - A Survey") is left alone.
_LINE_BREAK_HYPHEN = re.compile(r"(?<=\w)-\s+(?=\w)")

#: A tag, as Crossref keeps them from the publisher: "<i>In</i>-Situ". A tag
#: name must follow the bracket, so "Yield < 0 kg and > 5 kg" is left whole.
_MARKUP = re.compile(r"</?[A-Za-z][\w:.-]*(?:\s[^<>]*)?>")

#: Accents, whether combining or written as a letter of their own: PDF text
#: renders "Přerov" as "Pˇrerov", and the caron split the word in two.
_ACCENTS = re.compile(r"[\u0300-\u036f\u02b0-\u02ff\u00a8\u00b4\u00b8]")


def canonical_title(title: str | None) -> str:
    """Lowercase, join hyphens, drop all other punctuation, collapse spaces.

    Hyphens are JOINED rather than split: a bibliography may write
    "Multi-Layered Non-Woven" where the publisher records
    "Multilayered Nonwoven", and splitting turns a match into a miss.

    Line-break hyphenation is closed up FIRST, including the space after it.
    Titles read out of a PDF's own reference list arrive wrapped, so the
    store's "Producer-to-Consumer" meets the PDF's "producer- to-consumer".
    Only dropping the hyphen would leave "producer toconsumer" against
    "producertoconsumer" -- a miss on a paper already in hand.

    Markup and character entities go before anything: Crossref sends a title
    as HTML, "Trade &amp; Development", where the .bib wrote
    "Trade \\& Development", and the entity read as a word of its own.
    """
    if not title:
        return ""
    plain = html.unescape(_MARKUP.sub("", title))
    # NFKD spells a ligature out ("ﬁ" is "fi") and splits off accents.
    plain = _ACCENTS.sub("", unicodedata.normalize("NFKD", plain))
    joined = _LINE_BREAK_HYPHEN.sub("", plain.lower())
    lowered = joined.replace("-", "").replace("‐", "").replace("–", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", lowered).split())


#: Where a main title ends and a subtitle or qualifier begins: a colon, a
#: question or exclamation mark, a spaced or em dash, the designation ETSI
#: appends (", TS 23.501"), or a bracket that closes the title, as in
#: "(Release 17)". Not an unspaced dash, which is "Ages 2–4", and not a
#: bracket mid-title, which is an acronym: "Volatile Organic Compounds (VOCs)
#: in Urban Air" is not a paper called "Volatile Organic Compounds".
_SUBTITLE = re.compile(
    r"\s*(?::|\?|!|\s[-–—]\s|—|,\s*T[RS]\s+\d|[(\[](?=[^()\[\]]*[)\]]\s*$))")

#: The label ETSI puts in front of a 3GPP title it republishes: its "5G; NR;
#: Physical layer procedures for data" is 3GPP's "NR; Physical layer
#: procedures for data".
_ETSI_LABEL = re.compile(
    r"^\s*(?:5G|LTE|Universal Mobile Telecommunications System \(UMTS\))\s*;\s*",
    re.IGNORECASE)


def _main_titles(title: str) -> set[str]:
    """Each leading part of `title` that a subtitle follows, canonicalised."""
    return {canonical_title(title[:m.start()]) for m in _SUBTITLE.finditer(title)} - {""}


def titles_match(a: str | None, b: str | None) -> bool:
    """True when the two titles name the same work.

    Equal once canonicalised, or one is the other's main title with the
    subtitle left off: bibliographies drop subtitles and publishers add them.
    Containment anywhere was too much. A book called "Medieval Trade" would
    match a paper called "Venetian Glass and Medieval Trade" and be filed
    under it, and "Organic Chemistry" would match every paper whose title
    began that way. This decides which paper is filed under a citation, and
    filing the wrong one is worse than filing none, so anything else is a
    miss reported for fetching by hand.

    No spelling tolerance, deliberately. Forgiving a trailing "s" would let
    "Towards Phase 3 Vaccine Trials" match "Toward Phase 3 Vaccine Trials",
    which is the same paper retitled on publication -- and would cost nothing
    to allow. It is refused anyway, because the same latitude cannot be
    granted safely in general: "A Study of Urban Gardens" is not "A Study of
    Urban Garden Design".

    Guarded by a minimum length so a short main title cannot stand in for a
    long one: below it, only equal titles match.
    """
    a, b = _ETSI_LABEL.sub("", a or ""), _ETSI_LABEL.sub("", b or "")
    ca, cb = canonical_title(a), canonical_title(b)
    if not ca or not cb:
        return False
    if _letters(ca) == _letters(cb):
        return True
    if min(len(ca), len(cb)) < MIN_COMPARABLE:
        return False
    return (_says_enough(ca) and _letters(ca) in map(_letters, _main_titles(b))) or \
        (_says_enough(cb) and _letters(cb) in map(_letters, _main_titles(a)))


def _letters(canonical: str) -> str:
    """A canonical title without its spaces. A hyphen is joined, but the same
    compound written with a space -- "Cross-Laminated", "Cross Laminated" --
    is two words, and the two are one title."""
    return canonical.replace(" ", "")


def _says_enough(main: str) -> bool:
    """Whether a canonical main title is specific enough to stand for one with
    a subtitle. A textbook called "Organic Chemistry" against "Organic
    Chemistry: Methods and Applications" is two works, and the shorter title
    cannot tell them apart."""
    return len(main.split()) >= MAIN_TITLE_WORDS


def titles_overlap(a: str | None, b: str | None) -> bool:
    """True when one title's words appear, in order, inside the other's.

    Far looser than titles_match, and only for asking whether a DOI names the
    paper its entry describes: there the DOI is the identity and the title a
    check on it, and Crossref sometimes returns a shortened title. It never
    decides on its own which paper to file.

    The letters that overlap must be identical, and must begin and end where
    words of the longer title do, so "Design" cannot pass for "Designs". Only
    the spacing between may differ: Crossref writes "Cross Laminated" and
    "<i>In</i>\\n-Situ" where a .bib writes "Cross-Laminated" and "In-Situ".
    """
    ca, cb = canonical_title(a), canonical_title(b)
    if not ca or not cb:
        return False
    if min(len(ca), len(cb)) < MIN_COMPARABLE:
        return _letters(ca) == _letters(cb)

    short, long = sorted((ca, cb), key=lambda title: len(_letters(title)))
    wanted, letters = _letters(short), _letters(long)
    ends, at = {0}, 0
    for word in long.split():
        at += len(word)
        ends.add(at)
    return any(
        start in ends and start + len(wanted) in ends
        for start in range(len(letters) - len(wanted) + 1)
        if letters.startswith(wanted, start)
    )


#: The most lines a title is believed to wrap over on a first page.
TITLE_LINES = 4


def title_on_page(title: str | None, text: str) -> bool:
    """True when `title` stands on its own line or lines of `text`.

    The whole first page is searched, since a magazine can put its masthead,
    an ISSN and the abstract callout above the title. But the title has to
    begin and end a line -- or end where its subtitle starts -- rather than
    sit anywhere in the text: the masthead "ANNALS OF MEDIEVAL TRADE" would
    otherwise read as the title of the book "Medieval Trade", and a title
    named in an abstract as the paper's own.
    """
    wanted = canonical_title(title)
    if not wanted:
        return False
    whole, main = _titles_on(text)
    letters = _letters(wanted)
    return letters in whole or (_says_enough(wanted) and letters in main)


@lru_cache(maxsize=32)
def _titles_on(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """Every run of up to TITLE_LINES whole lines in `text`, canonicalised,
    and the main titles within them. Once per page, not once per reference
    the page is tried against."""
    lines = [line for line in text.splitlines() if line.strip()]
    whole: set[str] = set()
    main: set[str] = set()
    for first in range(len(lines)):
        for last in range(first + 1, min(first + TITLE_LINES, len(lines)) + 1):
            block = " ".join(lines[first:last])
            whole.add(_letters(canonical_title(block)))
            main |= {_letters(m) for m in _main_titles(block)}
    return frozenset(whole), frozenset(main)
