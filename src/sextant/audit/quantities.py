"""Claim prose -> the quantities a machine can look for.

A quantity is a number bound to a unit. A bare number is deliberately not
checkable: the falsification experiment showed that searching a paper for a
bare value passes essentially always, which produces confident nonsense.
"""

import re
from collections.abc import Collection, Sequence

from sextant.audit.models import Quantity

#: Units worth checking, longest first so "Mbit/s" wins over "Hz" and
#: "dBm" wins over "dB". Order in this tuple IS the alternation order.
_UNITS = (
    "Gbit/s", "Mbit/s", "kbit/s", "bit/s",
    "Gbps", "Mbps", "kbps",
    "dB/K", "dBm", "dBi", "dBW", "dB",
    "GHz", "MHz", "kHz", "Hz",
    "km", "ms", "mm", "cm",
    "kW", "mW", "W",
    "%",
)

_UNIT_ALT = "|".join(re.escape(u) for u in _UNITS)

#: A value as a manuscript writes one: 3, 0.5, or 1,000 with its thousands
#: grouped. Read digit by digit, 1,000 km was "000 km". A comma not followed by
#: three digits is a decimal one -- 3,5 GHz is 3.5 GHz -- so no value may start
#: just after a comma either, rather than misreading it as 5 GHz.
_VALUE = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"

# The value may be followed by optional whitespace before the unit. A bare
# number -- a year, a count -- is excluded by requiring the unit to be there.
_QTY = re.compile(rf"(?<![\w.,])({_VALUE})\s*({_UNIT_ALT})(?![a-zA-Z/])")

#: Spellings that mean the same unit. Keys are lowercase canonical forms.
#:
#: These are not cosmetic. A cited report wrote a unit with a negative
#: exponent, "1.1 dB K-1", where the manuscript citing it wrote "1.1 dB/K".
#: Without the equivalence Sextant reported the citation as unsupported -- a false
#: accusation against a correct citation, which is the worst thing it can do.
_VARIANTS = {
    "mbit/s": ("mbit/s", "mbps", "mb/s", "megabit/s"),
    "kbit/s": ("kbit/s", "kbps", "kb/s", "kilobit/s"),
    "gbit/s": ("gbit/s", "gbps", "gb/s", "gigabit/s"),
    "bit/s": ("bit/s", "bps", "b/s"),
    # ISO writes a reciprocal unit as "K-1" where a paper may write "/K".
    "db/k": ("db/k", "db k-1", "dbk-1", "db k\u22121", "dbk\u22121", "db/ k"),
}


def quantities(claim: str) -> list[Quantity]:
    """Every checkable number-plus-unit in `claim`, in order of appearance."""
    return [
        Quantity(value=m.group(1), unit=m.group(2), raw=m.group(0))
        for m in _QTY.finditer(claim)
    ]


def nowhere_note(unfound: Sequence[Quantity],
                 given_elsewhere: Collection[tuple[str, str]] = ()) -> str:
    """The figures beside a located one that no cited paper gives.

    A note, not a verdict. The one located still makes this a place for a
    reader to look, and a sentence can carry figures that are only context.
    `given_elsewhere` is what the other papers of a joint citation located:
    "20 ms and 5 Gbps [1], [2]" is not short of 5 Gbps because [1] lacks it.
    Worded unlike a not-found's reason, which the viewer drops as a restatement
    of its own sentence.
    """
    missing = [q for q in unfound if (q.value, q.unit) not in given_elsewhere]
    if not missing:
        return ""
    figures = ", ".join(f"{q.value} {q.unit}" for q in missing)
    return f"{figures}, also named in this sentence, is nowhere in the cited paper"


def unit_variants(unit: str) -> tuple[str, ...]:
    """Lowercase spellings that should all count as `unit`.

    Units not in the variant table stand alone: dB must not match dBm, so the
    default is the unit itself and nothing else.
    """
    return _VARIANTS.get(unit.lower(), (unit.lower(),))
