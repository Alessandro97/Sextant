"""Turn an office document into a PDF so the rest of Sextant can read it.

Everything downstream -- text extraction, span recovery, page rendering --
speaks PDF. A .doc dropped into the refs folder was previously invisible: the
glob skipped it and nothing said why.

3GPP publishes its specifications as .doc, and those are exactly the references
no resolver can fetch, so this is the format a user is most likely to add by
hand.
"""

import functools
import os
import re
import signal
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from sextant.dotenv import child_env
from sextant.safefs import real_dir

#: Formats LibreOffice can turn into a PDF for us.
CONVERTIBLE = {".doc", ".docx", ".rtf", ".odt", ".ppt", ".pptx"}

#: A large 3GPP specification is a slow conversion, not a hung one: one can
#: take about two minutes on an idle machine and run past 300 s on a busy one.
TIMEOUT = 600


class ConversionUnavailableError(Exception):
    """No converter is installed on this machine."""


def converter() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


@functools.cache
def _offline_prefix() -> tuple[str, ...]:
    """What runs the converter with no network, where the system allows one.

    The documents converted are ones someone sent. An .odt with a linked image
    had LibreOffice request the URL, telling its author who opened it and when,
    and reaching services on the reader's own network as it did. Linux user
    namespaces cut the network for one process with no privileges needed;
    elsewhere, or where they are turned off, the conversion runs as before.
    """
    unshare = shutil.which("unshare")
    if not unshare:
        return ()
    prefix = (unshare, "--user", "--net", "--map-root-user")
    try:
        probe = subprocess.run([*prefix, "true"], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ()
    return prefix if probe.returncode == 0 else ()


#: Where a reader's own files live. The sandbox hides all of it, then shows
#: the converter only the document, its output and its profile.
#: /run holds the session bus, the ssh-agent and display sockets; the rest
#: are where people keep files, or mount other machines' disks.
_PRIVATE = ("/home", "/root", "/tmp", "/var/tmp", "/run", "/media", "/mnt", "/srv",
            "/var/mail", "/var/spool", "/afs", "/net", "/nfs", "/data", "/scratch")


@functools.cache
def _sandbox() -> bool:
    """Whether bubblewrap can run a program here, with nothing shared.

    Cutting the network was not enough. A .docx linking file:///home/... had
    LibreOffice embed that file in the PDF it made, and the PDF is filed,
    stored, and shared with the folder it lands in.
    """
    if os.name == "nt" or not shutil.which("bwrap"):
        return False
    # With exactly a conversion's flags: where --proc is refused (a nested
    # container), a bare probe passed and every conversion then failed.
    with tempfile.TemporaryDirectory(prefix="sextant-probe-") as scratch:
        document = Path(scratch) / "probe.txt"
        document.write_text("probe")
        try:
            probe = subprocess.run([*_sandbox_prefix(str(document), scratch, scratch), "true"],
                                   capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
    return probe.returncode == 0


def _sandbox_prefix(document: str, scratch: str, profile: str) -> list[str]:
    """bubblewrap with no network and none of the reader's files: only the
    document itself (read-only), the output folder and the profile. Not the
    document's folder: a picture beside it could be embedded."""
    args = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
    hidden = [d for d in _PRIVATE if os.path.isdir(d)]
    home = str(Path.home().resolve())
    if not any(home == d or home.startswith(d + "/") for d in hidden):
        hidden.append(home)  # /var/home, say
    for directory in hidden:
        args += ["--tmpfs", directory]
    args += ["--ro-bind", document, document, "--bind", scratch, scratch,
             "--bind", profile, profile, "--unshare-all", "--die-with-parent"]
    return args


#: Targets a document may link to: the web, an address, a place in itself,
#: and names no file can answer to (cid: from mail, data: inline).
_WEB = ("http://", "https://", "mailto:", "#", "cid:", "data:")
#: Relationships that bring nothing in: a hyperlink is not followed, and the
#: template a document was written with -- every 3GPP specification names
#: its editor's, C:\\Users\\...\\3gpp_70.dot -- is not loaded.
_INERT = ("/hyperlink", "/attachedTemplate")
#: Larger than any package part worth reading; one this size is refused,
#: not skipped.
_MAX_PART = 5_000_000
_XLINK = "{http://www.w3.org/1999/xlink}href"


def _links_local_files(source: Path) -> bool:
    """Whether a document links a file on disk rather than embedding it.

    The format is read from the content, not the name: LibreOffice does the
    same, and a .docx renamed .doc slipped past a check by extension. This is
    a second line only. Where the converter cannot be sandboxed, a document
    someone sent is not converted at all.
    """
    try:
        head = source.read_bytes()[:8]
        if head.startswith(b"PK\x03\x04"):
            return _zip_links_local(source)
        if head.startswith(b"{\\rtf"):
            text = source.read_bytes().lower()
            return any(word in text for word in (b"includepicture", b"includetext", b"file:"))
    except (OSError, zipfile.BadZipFile):
        return True  # unreadable: assume the worst
    return False


def _zip_links_local(source: Path) -> bool:
    """Office XML keeps every outside link in its small .rels parts; ODF in
    content.xml and styles.xml, which are streamed: a 3GPP specification's
    body alone is over ten megabytes."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(source) as bundle:
        for info in bundle.infolist():
            name = info.filename.lower()
            if name.endswith(".rels"):
                if info.file_size > _MAX_PART:
                    return True
                try:
                    root = ET.fromstring(bundle.read(info))
                except ET.ParseError:
                    return True
                for element in root.iter():
                    if (element.get("TargetMode") == "External"
                            and not element.get("Type", "").endswith(_INERT)
                            and not element.get("Target", "").strip().lower().startswith(_WEB)):
                        return True
            elif name in ("content.xml", "styles.xml"):
                try:
                    with bundle.open(info) as part:
                        for _, element in ET.iterparse(part):
                            link = (element.get(_XLINK) or "").strip()
                            if link and not link.lower().startswith(_WEB) and (
                                    ":" in link or link.startswith(("/", "\\", ".."))
                                    or "../" in link):
                                return True
                            element.clear()
                except ET.ParseError:
                    return True
    return False


def _converter_env(profile: str) -> dict[str, str]:
    """Only what LibreOffice needs, with its home in a profile of its own.

    The reader's environment carries whatever credentials their shell exports,
    and a converter has no use for any of them. Windows needs its own
    variables merely to start a program, so there it keeps the usual ones.
    """
    if os.name == "nt":
        return child_env()
    kept = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TMPDIR")
            if name in os.environ}
    return {**kept, "HOME": profile}


def _run(argv: list[str], *, env: dict[str, str], timeout: float) -> subprocess.CompletedProcess:
    """Run the converter, and on timeout stop everything it started.

    subprocess.run kills only its own child, which here is unshare: when a
    large specification runs past the timeout, soffice.bin carries on,
    orphaned, converting into a folder already deleted. So the converter gets a session
    of its own, and the whole group goes when time is up.
    """
    posix = os.name != "nt"
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=env, start_new_session=posix)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if posix:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
        raise
    return subprocess.CompletedProcess(argv, process.returncode, out, err)


def to_pdf(source: Path, out_dir: Path, *, trusted: bool = False) -> Path:
    """Convert `source` to a PDF in `out_dir` and return the new path.

    A document someone sent is converted only in the sandbox. `trusted` is
    for a specification Sextant downloaded itself from the 3GPP archive, the
    one host it accepts them from: converted with the network cut where the
    sandbox is missing.

    Idempotent: an existing conversion newer than the source is reused, which
    matters because a large specification takes tens of seconds.
    """
    source = Path(source).resolve()
    out_dir = real_dir(out_dir)
    target = out_dir / f"{source.stem}.pdf"

    # A link waiting at the target is not an earlier conversion. It came with
    # the folder, and reusing it would hand over whatever it points at.
    if (target.is_file() and not target.is_symlink()
            and target.stat().st_mtime >= source.stat().st_mtime):
        return target

    binary = converter()
    if binary is None:
        raise ConversionUnavailableError(
            "no LibreOffice on this machine; save the document as PDF and drop "
            "that in instead"
        )
    sandboxed = _sandbox()
    if not sandboxed and not trusted:
        raise ConversionUnavailableError(
            f"not converting {source.name}: a document someone sent is converted only "
            "in a sandbox, which needs bubblewrap on Linux; save it as PDF and drop "
            "that in instead"
        )
    if _links_local_files(source):
        raise RuntimeError(
            f"not converting {source.name}: it links files on this computer, and "
            "converting would copy them into the PDF"
        )

    # Converted into a folder of its own and renamed into place, so a link at
    # the target is replaced rather than written through. With a profile of
    # its own as well: the reader's carries their macro and trusted-location
    # settings, and an instance they had open took the job and dropped it.
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".convert-") as scratch, \
            tempfile.TemporaryDirectory(prefix="sextant-office-") as profile:
        prefix = (_sandbox_prefix(str(source), scratch, profile) if sandboxed
                  else list(_offline_prefix()))
        result = _run(
            [*prefix, binary,
             f"-env:UserInstallation={Path(profile).as_uri()}",
             "--headless", "--convert-to", "pdf", "--outdir", scratch, str(source)],
            env=_converter_env(profile),
            timeout=TIMEOUT,
        )
        made = Path(scratch) / f"{source.stem}.pdf"
        if not made.exists():
            detail = (result.stderr or result.stdout or "").strip()[:300]
            raise RuntimeError(f"could not convert {source.name}: {detail}")
        os.replace(made, target)
    return target
