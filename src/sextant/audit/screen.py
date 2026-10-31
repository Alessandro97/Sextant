"""Locate a claimed quantity inside a cited paper's text layer.

MEASURED BEHAVIOUR (2026-08-06, on the real manuscript): requiring the value to
sit adjacent to its unit finds 7 of 7 true claims and admits 1 of 14 perturbed
ones. Searching for the bare value instead finds 7 of 7 and admits 14 of 14 --
it accepts everything. Do not loosen the adjacency requirement.

The surviving false positive is a broad survey that mentions the same figure
in a passage unrelated to the claim citing it. No adjacency rule can exclude that;
only a reader can, which is why a hit is reported as a location to check.

A hit is NOT evidence that the paper supports the claim. It is a pointer to the
page a human should read. Absence is the confident signal.
"""

import re
from collections.abc import Sequence

from sextant.audit.models import Quantity
from sextant.audit.quantities import unit_variants
from sextant.index.locate import rects_for_range
from sextant.models import Page, Span

#: Characters tolerated between the value and its unit: whitespace, a
#: non-breaking space, a hyphen. Not a letter and not another digit.
_GAP = r"[\s \-]{0,3}"


#: What a paper may group thousands with: a comma, a thin or no-break space,
#: or a plain space where extraction flattened one of those.
_THOUSANDS = r"[,\u2009\u202f\u00a0 ]?"


def _value(value: str) -> str:
    """`value` however a paper might print the same number.

    Grouped or not, and with or without trailing zeros. Missing 2 GHz in a
    paper that says 2.0 GHz, or 1,000 km in one that says 1000 km, accused a
    correct citation -- the worst thing this can do. The digits themselves
    still have to agree, so 2.5 and 20 stay different numbers.
    """
    whole, _, fraction = value.replace(",", "").partition(".")
    whole = whole.lstrip("0") or "0"
    head = len(whole) % 3 or 3
    groups = [whole[:head]] + [whole[i:i + 3] for i in range(head, len(whole), 3)]
    fraction = fraction.rstrip("0")
    return (_THOUSANDS.join(groups)
            + (rf"\.{fraction}0*" if fraction else r"(?:\.0+)?"))


def _pattern(quantity: Quantity) -> re.Pattern[str]:
    value = _value(quantity.value)
    units = "|".join(re.escape(u) for u in unit_variants(quantity.unit))
    # (?<![\d.]) and (?![\d]) stop 20 from matching inside 120 or 20.5.
    # (?![a-z/]) stops dB from matching dBm or dB/K.
    #
    # A comma before the value is allowed. Refusing it, so that "3,20" written
    # for 3.20 would not point at 20, turned "5,10,20 ms" into a not-found:
    # trading a wrong pointer for an accusation, which is the wrong way round.
    return re.compile(
        rf"(?<![\d.]){value}(?![\d]){_GAP}(?:{units})(?![a-z/])",
        re.IGNORECASE,
    )


def screen(quantity: Quantity, pages: Sequence[Page]) -> Span | None:
    """First page where `quantity` appears with its unit, or None.

    Returning None means the quantity is absent from the whole document, which
    is the finding worth acting on.
    """
    pattern = _pattern(quantity)

    for page in pages:
        match = pattern.search(page.text)
        if match is None:
            continue
        return Span(
            page=page.number,
            char_start=match.start(),
            char_end=match.end(),
            rects=rects_for_range(page, match.start(), match.end()),
        )

    return None


#: A quantity like "0 dB" can occur dozens of times in a long specification.
#: Painting every one turns the page into a highlighter accident and tells the
#: reader nothing, so the list is capped and the true total reported alongside.
MAX_OCCURRENCES = 25


def screen_all(
    quantity: Quantity, pages: Sequence[Page], limit: int = MAX_OCCURRENCES
) -> tuple[list[Span], int]:
    """Every place `quantity` appears with its unit, and how many there are.

    screen() answers "is it there at all", which is what a verdict needs. A
    reader checking a citation wants the other answer: where, everywhere, so
    they can see whether the one the tool picked is the relevant one.
    """
    pattern = _pattern(quantity)
    spans: list[Span] = []
    total = 0

    for page in pages:
        for match in pattern.finditer(page.text):
            total += 1
            if len(spans) >= limit:
                continue
            spans.append(
                Span(
                    page=page.number,
                    char_start=match.start(),
                    char_end=match.end(),
                    rects=rects_for_range(page, match.start(), match.end()),
                )
            )

    return spans, total


def excerpt_around(text: str, start: int, end: int, width: int = 90) -> str:
    """The quantity plus surrounding context, for a human to judge.

    A located quantity is only useful if the reader can see what sentence it
    sits in, so the report always carries this alongside the page number.
    """
    lo = max(0, start - width)
    hi = min(len(text), end + width)
    return " ".join(text[lo:hi].split())
