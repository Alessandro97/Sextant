"""arXiv: title search over the Atom API.

Two things to know. The API answers http:// with a 301, so redirects must be
followed (HttpFetcher does). And the feed carries its own <title> element that
merely echoes the query — parsing must look inside <entry> only, or every
search appears to succeed.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode

from sextant.refs.http import Fetcher
from sextant.refs.models import BibEntry, Resolution
from sextant.refs.resolvers.copies import Copy, fetch_first, version_note
from sextant.refs.titles import titles_match, titles_overlap

BASE = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"

#: Enough words to single out a paper; more only lengthen the query.
QUERY_WORDS = 12

#: Words a title search must not require: "ti:for AND ti:the ..." matched
#: nothing for papers that are on arXiv.
_UNSEARCHED = frozenset(
    "a an and are as at be by can do does for from in into is it its not of on or "
    "our that the their this to via we with".split())


class ArxivResolver:
    name = "arxiv"

    def search_url(self, title: str) -> str:
        # Every word, not the exact phrase: the phrase missed "Cross-Laminated"
        # against "Cross Laminated". titles_match decides what is kept.
        words = [w for w in re.findall(r"[A-Za-z0-9]+", title)
                 if len(w) > 1 and w.lower() not in _UNSEARCHED]
        query = " AND ".join(f"ti:{w}" for w in words[:QUERY_WORDS])
        return f"{BASE}?{urlencode({'search_query': query, 'max_results': '3'})}"

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution:
        if not entry.title:
            return Resolution(key=entry.key, status="unresolved",
                              reason="no title to search on")

        if not re.search(r"[A-Za-z0-9]{2}", entry.title):
            return Resolution(key=entry.key, status="unresolved",
                              reason="nothing in the title to search arXiv on")

        feed = fetcher.text(self.search_url(entry.title))
        if not feed:
            return Resolution(key=entry.key, status="unresolved",
                              reason="no response from arxiv")

        try:
            root = ET.fromstring(feed)
        except ET.ParseError:
            return Resolution(key=entry.key, status="unresolved",
                              reason="malformed feed")

        # Only <entry> children. The feed's own <title> echoes the query.
        notes: list[str] = []
        similar: list[str] = []
        retry = False
        for element in root.findall(f"{ATOM}entry"):
            found = " ".join((element.findtext(f"{ATOM}title") or "").split())
            if not titles_match(entry.title, found):
                # One title inside the other -- a preprint retitled on
                # publication, or a different paper. A person decides.
                page = (element.findtext(f"{ATOM}id") or "").strip()
                if page and titles_overlap(entry.title, found):
                    similar.append(f"{found} — {page.replace('http://', 'https://', 1)}")
                continue
            copies = [Copy(link.get("href"), version="submittedVersion", source="arXiv",
                           keyed_by_doi=False)
                      for link in element.findall(f"{ATOM}link")
                      if link.get("title") == "pdf" and link.get("href")]
            got, more, busy = fetch_first(entry, copies, fetcher, dest_dir)
            notes += more
            retry = retry or busy
            if got:
                return Resolution(key=entry.key, status="resolved",
                                  title=found, pdf_path=str(got.path), version=got.copy.version,
                                  reason=version_note(got.copy),
                                  resolver=self.name)

        return Resolution(key=entry.key, status="unresolved", similar=tuple(similar), retry=retry,
                          reason="; ".join(notes) or "no matching arxiv entry")
