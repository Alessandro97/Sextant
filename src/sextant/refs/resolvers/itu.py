"""ITU-R Recommendations: recognised, and linked to their own page.

"Free online access to all current ITU-R Recommendations and Reports is now
provided to the general public" (https://www.itu.int/pub/R-REC), but ITU
documents no address a program can download one from: the pages build their
links in JavaScript. So the reader gets the page, one click from the PDF.
"""

import re
from pathlib import Path

from sextant.refs.http import Fetcher
from sextant.refs.models import BibEntry, Resolution

# "ITU-R P.525", "itu_p525", "ITU-R_P1546": one of ITU-R's own series letters
# and a number, after ITU's name -- never a bare letter and number, which any
# key has. "Ebola in Ituri 2019" is not a recommendation, nor is ITU-T G.711.
_SERIES = "BO|BR|BS|BT|F|M|P|RA|RS|SA|SF|SM|SNG|S|TF|V"
_REC = re.compile(rf"\bitu(?:[-_ ]?r)?[-_ ]?({_SERIES})[._ ]?(\d{{2,4}})(?!\d)", re.I)
_ITU_T = re.compile(r"\bitu[-_ ]?t\b", re.I)


def recommendation(title: str | None, key: str | None) -> str | None:
    """"P.525" for an ITU-R Recommendation, or None."""
    if _ITU_T.search(f"{title or ''} {key or ''}"):
        return None
    for text in (title, key):
        match = _REC.search(text or "")
        if match:
            return f"{match.group(1).upper()}.{match.group(2)}"
    return None


class ItuResolver:
    name = "itu"

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution:
        number = recommendation(entry.title, entry.key)
        if number is None:
            return Resolution(key=entry.key, status="unresolved",
                              reason="not an ITU-R Recommendation")
        return Resolution(
            key=entry.key, status="no-pdf", title=entry.title, final=True,
            reason=f"ITU-R {number}: free from ITU, which offers no address a "
                   "program can download it from",
            landing_pages=(f"https://www.itu.int/rec/R-REC-{number}/en",),
        )
