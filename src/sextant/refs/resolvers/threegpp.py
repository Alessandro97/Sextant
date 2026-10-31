"""3GPP specifications, downloaded from the 3GPP archive and converted.

The archive lists one zip per version, each holding the Word document.
Measured 2026-08-06, the listing could not be scraped and ETSI's own copies
answered scripts with 403, so this only linked to the archive. Measured again
2026-10-31: the listing is plain HTML and the zips download without a login.

Zip names code the version in base 36 -- 23501-h30.zip is v17.3.0 -- or, for
a spec past 35 versions, in six digits: 24229-083700.zip. "Once under change
control, the major field indicates the Release."
(https://www.3gpp.org/specifications-technologies/specifications-by-series/file-name-conventions)
"""

import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urljoin

from sextant.refs.convert import converter, to_pdf
from sextant.refs.folder import key_pdf
from sextant.refs.http import Fetcher, Unavailable
from sextant.refs.inbox import cover_spec_numbers, first_page_text
from sextant.refs.models import BibEntry, Resolution
from sextant.safefs import real_dir

# "TR 21.905", "TS 23.501", and the dotless "ts_23501" that appears in keys.
#
# The leading guard is a negative lookbehind for a LETTER, not \b. Underscore
# is a word character, so \b never fires inside "3gpp_ts_23501" — a form
# citation keys commonly take. The lookbehind still prevents matching the
# "tr" inside a word like "attr".
_SPEC = re.compile(r"(?<![a-zA-Z])(TR|TS)[\s_-]*(\d{2})[._ ]?(\d{3})(?!\d)", re.I)

#: A number alone -- "23501", "3gpp_21.905" -- names a spec only where the
#: entry says it is 3GPP's, or cites a Release the way 3GPP titles do.
_NUMBER = re.compile(r"(?<!\d)(\d{2})[._]?(\d{3})(?!\d)")
# A letter guard, not \b, for the same reason as _SPEC: "3gpp_23501_rel16".
_THREEGPP = re.compile(r"3gpp|\(release \d+\)|(?<![a-z])rel(?:ease)?[-_ .]*\d+(?!\d)", re.I)
_RELEASE = re.compile(r"(?<![a-z])rel(?:ease)?[-_ .]*(\d{1,2})(?!\d)", re.I)
_EXACT = re.compile(r"\bV(\d{1,2})\.(\d{1,2})\.(\d{1,2})\b")
#: The only host a specification is downloaded from, whatever a listing links.
ARCHIVE = "https://www.3gpp.org/ftp/Specs/archive/"

#: Larger than any specification's Word file; a zip claiming more is refused
#: rather than unpacked.
MAX_DOCUMENT_BYTES = 300 * 1024 * 1024


def spec_number(title: str | None, key: str | None = None) -> tuple[str, str] | None:
    """("TR", "21.905"), ("", "23.501") for a bare number, or None."""
    for text in (title, key):
        match = _SPEC.search(text or "")
        if match:
            kind, series, number = match.groups()
            return kind.upper(), f"{series}.{number}"
    context = f"{title or ''} {key or ''}"
    if _THREEGPP.search(context):
        for text in (key, title):
            match = _NUMBER.search(text or "")
            if match:
                return "", f"{match.group(1)}.{match.group(2)}"
    return None


def archive_url(number: str) -> str:
    series = number.split(".")[0]
    return f"{ARCHIVE}{series}_series/{number}/"


def _version(code: str) -> tuple[int, int, int]:
    if len(code) == 6:
        return int(code[:2]), int(code[2:4]), int(code[4:])
    return tuple(int(c, 36) for c in code)


class ThreeGppResolver:
    name = "3gpp"

    def resolve(
        self, entry: BibEntry, fetcher: Fetcher, dest_dir: Path
    ) -> Resolution:
        found = spec_number(entry.title, entry.key)
        if found is None:
            return Resolution(key=entry.key, status="unresolved",
                              reason="not a 3GPP/ETSI specification")

        kind, number = found
        label = f"{kind} {number}".strip()
        portal = archive_url(number)

        def link_only(why: str, retry: bool = False) -> Resolution:
            return Resolution(key=entry.key, status="no-pdf", reason=f"{label}: {why}",
                              title=entry.title, landing_pages=(portal,), retry=retry,
                              final=True)

        # The archive holds Word files. Without a converter there is nothing
        # to do with one, so nothing is downloaded.
        if converter() is None:
            return link_only("the archive holds Word files, and converting them "
                             "needs LibreOffice")

        listing = fetcher.text(portal)
        versions = _zips(listing or "", number, portal)
        if not versions:
            return link_only("the archive lists no version of it")

        cited = f"{entry.title or ''} {entry.key}"
        exact = _EXACT.search(cited)
        wanted = _RELEASE.search(cited)
        if exact:
            version_wanted = tuple(int(n) for n in exact.groups())
            versions = [v for v in versions if v[0] == version_wanted] or versions
        elif wanted:
            release = int(wanted.group(1))
            versions = [v for v in versions if v[0][0] == release] or versions
        version, url = max(versions)
        shown = "V{}.{}.{}".format(*version)

        with tempfile.TemporaryDirectory(dir=real_dir(dest_dir), prefix=".3gpp-") as scratch:
            scratch = Path(scratch)
            archive = scratch / "spec.zip"
            try:
                if not fetcher.download(url, archive, expect=b"PK"):
                    return link_only(f"{shown} would not download")
            except Unavailable as exc:
                return link_only(f"{shown}: no answer ({exc}), try again later", retry=True)
            try:
                document = _extract(archive, scratch)
            except (zipfile.BadZipFile, ValueError) as exc:
                return link_only(f"{shown}: {exc}")
            try:
                pdf = to_pdf(document, scratch, trusted=True)
            except Exception as exc:  # a converter failure is not a crash
                return link_only(f"{shown} could not be converted ({type(exc).__name__})")
            if number not in cover_spec_numbers(first_page_text(pdf)):
                return link_only(f"the converted {shown} does not show {label} on its cover")
            dest = key_pdf(dest_dir, entry.key)
            os.replace(pdf, dest)

        return Resolution(key=entry.key, status="resolved", title=entry.title,
                          pdf_path=str(dest), resolver=self.name,
                          reason=f"{label} {shown} (Release {version[0]}), converted "
                                 "from the 3GPP archive's Word file",
                          landing_pages=(portal,))


def _zips(listing: str, number: str, portal: str) -> list[tuple[tuple[int, int, int], str]]:
    """Every (version, url) the archive listing offers for `number`."""
    digits = number.replace(".", "")
    found = []
    for href, code in re.findall(
            rf'href="([^"]*?{digits}-([0-9a-z]{{3}}|\d{{6}})\.zip)"', listing):
        url = urljoin(portal, href)
        if url.startswith(ARCHIVE):
            found.append((_version(code), url))
    return found


def _extract(archive: Path, into: Path) -> Path:
    """The specification's Word file, by its base name only, within the cap."""
    with zipfile.ZipFile(archive) as bundle:
        documents = [m for m in bundle.infolist()
                     if Path(m.filename).suffix.lower() in (".doc", ".docx")]
        if not documents:
            raise ValueError("the zip holds no Word file")
        member = max(documents, key=lambda m: m.file_size)
        if member.file_size > MAX_DOCUMENT_BYTES:
            raise ValueError("the zip's Word file is implausibly large")
        # The name inside a zip can climb out of the folder ("../../x").
        target = into / Path(member.filename.replace("\\", "/")).name
        # zipfile stops reading a member at the size its header declares, so
        # the check above bounds what is written.
        with bundle.open(member) as source, open(target, "wb") as out:
            shutil.copyfileobj(source, out)
    return target
