import os
import subprocess
import time
from pathlib import Path

import pytest

from sextant.refs.convert import CONVERTIBLE, converter, to_pdf

pytestmark = pytest.mark.skipif(converter() is None, reason="no LibreOffice")


def _rtf(path: Path, text: str) -> Path:
    """RTF is a real office format LibreOffice converts, and writable as text."""
    path.write_text(r"{\rtf1\ansi " + text + "}")
    return path


def test_converts_an_office_document_to_a_readable_pdf(tmp_path):
    source = _rtf(tmp_path / "spec.rtf", "Guidelines for archiving field survey data")

    pdf = to_pdf(source, tmp_path / "out", trusted=True)

    assert pdf.suffix == ".pdf"
    assert pdf.read_bytes().startswith(b"%PDF")


def test_the_converted_pdf_carries_the_text(tmp_path):
    import pymupdf

    source = _rtf(tmp_path / "spec.rtf", "Guidelines for archiving field survey data")

    doc = pymupdf.open(to_pdf(source, tmp_path / "out", trusted=True))
    try:
        assert "Guidelines for archiving" in doc[0].get_text()
    finally:
        doc.close()


def test_conversion_is_reused_rather_than_repeated(tmp_path):
    """A large specification takes tens of seconds; doing it on every
    rescan would make Update feel broken."""
    source = _rtf(tmp_path / "spec.rtf", "some text")
    first = to_pdf(source, tmp_path / "out", trusted=True)
    stamp = first.stat().st_mtime_ns

    second = to_pdf(source, tmp_path / "out", trusted=True)

    assert second == first
    assert second.stat().st_mtime_ns == stamp, "should not have re-converted"


def test_the_source_document_is_left_alone(tmp_path):
    source = _rtf(tmp_path / "spec.rtf", "text")
    before = source.read_bytes()

    to_pdf(source, tmp_path / "out", trusted=True)

    assert source.exists() and source.read_bytes() == before


def test_doc_is_among_the_formats_we_offer_to_convert():
    """3GPP publishes specifications as .doc, and those are exactly the
    references no resolver can fetch."""
    assert ".doc" in CONVERTIBLE and ".docx" in CONVERTIBLE


def test_rescan_converts_documents_without_being_asked_first(tmp_path):
    """rescan_folder is self-contained: a caller that hands it a folder gets
    the office documents in it considered, without a separate step."""
    from sextant.refs.models import Resolution
    from sextant.refs.pipeline import rescan_folder

    refs = tmp_path / "refs"
    (refs / "inbox").mkdir(parents=True)
    _rtf(refs / "spec.rtf", "A Very Specific Standards Document Title")

    rescan_folder(refs, [Resolution(key="k", status="unresolved",
                                    title="A Very Specific Standards Document Title")])

    assert (refs / "inbox" / "spec.pdf").exists(), "should have converted on its own"


def test_converting_twice_does_no_work_the_second_time(tmp_path):
    """The route converts to report what happened, then rescan_folder converts
    again for self-containment. That must be free, not a second long wait."""
    from sextant.refs.pipeline import convert_dropped_documents

    refs = tmp_path / "refs"
    (refs / "inbox").mkdir(parents=True)
    _rtf(refs / "spec.rtf", "Some Document")

    convert_dropped_documents(refs)
    stamp = (refs / "inbox" / "spec.pdf").stat().st_mtime_ns
    convert_dropped_documents(refs)

    assert (refs / "inbox" / "spec.pdf").stat().st_mtime_ns == stamp


def test_libreoffice_is_not_handed_a_key_from_dotenv(tmp_path, monkeypatch):
    """The file promises no other program inherits the key."""
    import subprocess

    import sextant.dotenv as dotenv
    from sextant.refs import convert

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-file")
    monkeypatch.setattr(dotenv, "_from_file", {"ANTHROPIC_API_KEY"})
    monkeypatch.setattr(convert, "converter", lambda: "soffice")
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        outdir = argv[argv.index("--outdir") + 1]
        (convert.Path(outdir) / "spec.pdf").write_bytes(b"%PDF-1.7")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(convert, "_run", fake_run)
    source = tmp_path / "spec.docx"
    source.write_bytes(b"not really a docx")

    convert.to_pdf(source, tmp_path / "out", trusted=True)

    assert "ANTHROPIC_API_KEY" not in seen["env"]


def _capture_soffice(tmp_path, monkeypatch):
    import subprocess

    from sextant.refs import convert

    monkeypatch.setattr(convert, "converter", lambda: "soffice")
    seen = {}

    def fake_run(argv, **kwargs):
        if "--outdir" not in argv:          # the probe for a network namespace
            return subprocess.CompletedProcess(argv, 0, "", "")
        seen["argv"], seen["env"] = argv, kwargs["env"]
        outdir = argv[argv.index("--outdir") + 1]
        (convert.Path(outdir) / "spec.pdf").write_bytes(b"%PDF-1.7")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(convert, "_run", fake_run)
    source = tmp_path / "spec.docx"
    source.write_bytes(b"a document")
    convert.to_pdf(source, tmp_path / "out", trusted=True)
    return seen


def test_libreoffice_runs_with_a_profile_of_its_own(tmp_path, monkeypatch):
    """The reader's profile carries their macro and trusted-location settings,
    and an instance they have open swallows the job: the conversion came back
    empty-handed whenever LibreOffice was already running."""
    seen = _capture_soffice(tmp_path, monkeypatch)

    profiles = [a for a in seen["argv"] if a.startswith("-env:UserInstallation=file://")]
    assert len(profiles) == 1
    assert seen["env"].get("HOME") != str(Path.home())


def test_libreoffice_is_not_handed_the_readers_credentials(tmp_path, monkeypatch):
    import os

    if os.name == "nt":
        pytest.skip("Windows needs its own variables to start a program at all")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "exported-in-the-shell")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "exported-in-the-shell")

    seen = _capture_soffice(tmp_path, monkeypatch)

    assert "AWS_SECRET_ACCESS_KEY" not in seen["env"]
    assert "ANTHROPIC_API_KEY" not in seen["env"]
    assert seen["env"]["PATH"] == os.environ["PATH"]


def test_a_document_cannot_make_libreoffice_fetch_a_url(tmp_path):
    """An .odt someone sent, with a linked image: converting it made
    LibreOffice request the URL, telling its author who opened it and when."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from sextant.refs import convert

    if not convert._offline_prefix():
        pytest.skip("no network namespace on this system")
    hits = []

    class Beacon(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Beacon)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/beacon.png"
    source = tmp_path / "spec.fodt"
    source.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
 xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
 xmlns:xlink="http://www.w3.org/1999/xlink" office:version="1.3"
 office:mimetype="application/vnd.oasis.opendocument.text">
 <office:body><office:text><text:p>A reference paper.
  <draw:frame svg:width="2cm" svg:height="2cm" text:anchor-type="as-char">
   <draw:image xlink:href="{url}" xlink:type="simple" xlink:show="embed"
    xlink:actuate="onLoad"/></draw:frame></text:p></office:text></office:body>
</office:document>""")
    try:
        convert.to_pdf(source, tmp_path / "out", trusted=True)
    finally:
        server.shutdown()

    assert hits == []


@pytest.mark.skipif(os.name == "nt", reason="process groups are a POSIX notion")
@pytest.mark.parametrize("sandboxed", [False, True])
def test_a_conversion_that_times_out_leaves_no_libreoffice_behind(tmp_path, monkeypatch, sandboxed):
    """A large specification can run past the timeout, and only the wrapper
    was killed: soffice.bin ran on, orphaned, converting into a folder already
    deleted, for as long as it liked."""
    from sextant.refs import convert

    if sandboxed and not convert._sandbox():
        pytest.skip("no working bubblewrap here")
    monkeypatch.setattr(convert, "_sandbox", lambda: sandboxed)
    if sandboxed:  # the stand-in converter lives where the sandbox hides things
        real_prefix = convert._sandbox_prefix
        monkeypatch.setattr(convert, "_sandbox_prefix", lambda *a: [
            *real_prefix(*a)[:-2], "--ro-bind", str(tmp_path), str(tmp_path), *real_prefix(*a)[-2:]])
    pidfile = tmp_path / "grandchild.pid"
    script = tmp_path / "soffice"
    script.write_text(f"#!/bin/sh\nsleep 60 &\necho $! > {pidfile}\nwait\n")
    script.chmod(0o755)
    monkeypatch.setattr(convert, "converter", lambda: str(script))
    monkeypatch.setattr(convert, "TIMEOUT", 1)
    source = tmp_path / "spec.docx"
    source.write_bytes(b"a document")

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        convert.to_pdf(source, tmp_path / "out", trusted=True)
    assert time.monotonic() - started < 15, "waited on the converter's children"
    if sandboxed:
        return  # its own PID namespace: the sandbox cannot write the pid out,
                # and --die-with-parent takes the namespace down with it

    grandchild = int(pidfile.read_text())
    for _ in range(50):
        if _gone(grandchild):
            break
        time.sleep(0.1)
    else:
        os.kill(grandchild, 9)
        pytest.fail("the converter's own children outlived the timeout")



def _gone(pid: int) -> bool:
    """Dead or a zombie. Read in one step: checking that /proc/<pid> exists
    and then reading its stat raced the very exit being waited for."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
    except FileNotFoundError:
        return True

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _docx_linking(path, image_uri):
    """A .docx whose only picture is linked from `image_uri`, not embedded."""
    import zipfile

    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{_W}" xmlns:r="{_R}"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>
<w:p><w:r><w:t>A cover page</w:t></w:r></w:p>
<w:p><w:r><w:drawing><wp:inline><wp:extent cx="1905000" cy="571500"/><wp:docPr id="1" name="p"/>
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
<pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="p"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:link="rIdImg"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1905000" cy="571500"/></a:xfrm><a:prstGeom prst="rect"/></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p></w:body></w:document>"""
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""")
        bundle.writestr("_rels/.rels", f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="{_R}/officeDocument" Target="word/document.xml"/></Relationships>""")
        bundle.writestr("word/document.xml", document)
        bundle.writestr("word/_rels/document.xml.rels", f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdImg" Type="{_R}/image" Target="{image_uri}" TargetMode="External"/>
</Relationships>""")
    return path


def _secret_png(path):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=200, height=60)
    page.insert_text((10, 35), "DUMMY-SECRET", fontsize=16)
    path.write_bytes(page.get_pixmap().tobytes("png"))
    return path


def test_a_document_cannot_pull_a_file_from_elsewhere_on_this_computer(tmp_path, monkeypatch):
    """A .docx linking file:///home/.../secret.png had LibreOffice embed it in
    the PDF, which is then filed, stored, and shared with the folder. The
    network was cut; the disk was not."""
    from sextant.refs import convert

    if not convert._sandbox():
        pytest.skip("no working bubblewrap here")
    monkeypatch.setattr(convert, "_links_local_files", lambda source: False)  # the sandbox alone
    secret = _secret_png((tmp_path / "elsewhere").mkdir() or tmp_path / "elsewhere" / "secret.png")
    (tmp_path / "doc").mkdir()
    docx = _docx_linking(tmp_path / "doc" / "spec.docx", secret.as_uri())

    import pymupdf
    pdf = pymupdf.open(convert.to_pdf(docx, tmp_path / "out"))

    assert "A cover page" in pdf[0].get_text()
    assert pdf[0].get_images() == []


def test_an_office_file_that_links_files_on_this_computer_is_refused(tmp_path):
    from sextant.refs import convert

    docx = _docx_linking(tmp_path / "spec.docx", (tmp_path / "secret.png").as_uri())

    with pytest.raises(RuntimeError, match="files on this computer"):
        convert.to_pdf(docx, tmp_path / "out", trusted=True)


def test_an_office_file_that_links_the_web_is_converted(tmp_path):
    """Hyperlinks are external relationships too, and every paper has them."""
    from sextant.refs import convert

    assert not convert._links_local_files(_docx_linking(tmp_path / "s.docx", "https://example.org/a.png"))


def test_a_home_outside_home_is_hidden_too(monkeypatch):
    """Fedora Atomic keeps homes in /var/home."""
    from sextant.refs import convert

    monkeypatch.setattr(convert.Path, "home", classmethod(lambda cls: Path("/var/home/reader")))
    args = convert._sandbox_prefix("/doc/spec.docx", "/out", "/profile")

    assert args[args.index("/var/home/reader") - 1] == "--tmpfs"
    assert args.index("/var/home/reader") < args.index("/doc/spec.docx"), "hidden before the binds"


def test_the_sandbox_hides_the_session_and_the_documents_neighbours(tmp_path):
    """/run/user held the session bus and the ssh-agent socket, and a PNG
    beside the document could still be embedded."""
    from sextant.refs import convert

    args = convert._sandbox_prefix(str(tmp_path / "doc" / "spec.docx"), "/out", "/profile")

    hidden = {args[i + 1] for i, a in enumerate(args) if a == "--tmpfs"}
    assert {"/run", "/var/mail", "/var/spool"} & set(convert._PRIVATE) == {"/run", "/var/mail", "/var/spool"}
    assert "/run" in hidden or not os.path.isdir("/run")
    binds = [args[i + 1] for i, a in enumerate(args) if a == "--ro-bind"]
    assert str(tmp_path / "doc" / "spec.docx") in binds, "the document itself, not its folder"
    assert str(tmp_path / "doc") not in binds


def test_the_sandbox_probe_uses_the_flags_a_conversion_does(monkeypatch):
    """Where --proc fails, a bare probe passed and every conversion failed."""
    from sextant.refs import convert

    seen = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "", "")

    convert._sandbox.cache_clear()
    monkeypatch.setattr(convert.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(convert.subprocess, "run", run)
    try:
        convert._sandbox()
    finally:
        convert._sandbox.cache_clear()

    assert {"--proc", "--dev", "--tmpfs", "--unshare-all"} <= set(seen["argv"])


def test_without_a_sandbox_a_document_someone_sent_is_not_converted(tmp_path, monkeypatch):
    """Without bubblewrap a link check was all that stood between a document
    and the reader's files, and it fell to a renamed .docx, single quotes, an
    entity, an .odt and an .rtf. So it is not relied on: such a document is
    asked for as a PDF instead."""
    from sextant.refs import convert

    monkeypatch.setattr(convert, "_sandbox", lambda: False)
    docx = tmp_path / "spec.docx"
    docx.write_bytes(b"PK\x03\x04 a document")

    with pytest.raises(convert.ConversionUnavailableError, match="sandbox"):
        convert.to_pdf(docx, tmp_path / "out")


def test_without_a_sandbox_a_specification_from_the_3gpp_archive_is_converted(tmp_path, monkeypatch):
    from sextant.refs import convert

    monkeypatch.setattr(convert, "_sandbox", lambda: False)

    def run(argv, **kwargs):
        outdir = argv[argv.index("--outdir") + 1]
        (Path(outdir) / "23501-i40.pdf").write_bytes(b"%PDF-1.7")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(convert, "_run", run)
    doc = tmp_path / "23501-i40.doc"
    doc.write_bytes(b"\xd0\xcf\x11\xe0 a Word file")

    assert convert.to_pdf(doc, tmp_path / "out", trusted=True).exists()


def _zipped(path, members):
    import zipfile

    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return path


@pytest.mark.parametrize("name, members", [
    ("renamed.doc", {"word/_rels/document.xml.rels":
        '<Relationships><Relationship Id="r" Target="file:///home/u/s.png" TargetMode="External"/></Relationships>'}),
    ("quoted.docx", {"word/_rels/document.xml.rels":
        "<Relationships><Relationship Id='r' Target='file:///home/u/s.png' TargetMode='External'/></Relationships>"}),
    ("entity.docx", {"word/_rels/document.xml.rels":
        '<Relationships><Relationship Id="r" Target="file:///home/u/s.png" TargetMode="&#69;xternal"/></Relationships>'}),
    ("drawing.odt", {"content.xml":
        '<o xmlns:xlink="http://www.w3.org/1999/xlink"><i xlink:href="file:///home/u/s.png"/></o>'}),
])
def test_every_spelling_of_a_local_link_is_caught(tmp_path, name, members):
    from sextant.refs import convert

    assert convert._links_local_files(_zipped(tmp_path / name, members))


def test_an_rtf_that_includes_a_picture_from_disk_is_caught(tmp_path):
    from sextant.refs import convert

    rtf = tmp_path / "x.rtf"
    rtf.write_bytes(rb'{\rtf1 {\field{\*\fldinst INCLUDEPICTURE "file:///home/u/s.png" \\d}}}')

    assert convert._links_local_files(rtf)


def test_an_odt_with_its_own_pictures_and_web_links_is_fine(tmp_path):
    from sextant.refs import convert

    odt = _zipped(tmp_path / "x.odt", {"content.xml":
        '<o xmlns:xlink="http://www.w3.org/1999/xlink"><i xlink:href="Pictures/a.png"/>'
        '<a xlink:href="https://example.org"/><a xlink:href="#section"/></o>'})

    assert not convert._links_local_files(odt)


def test_a_package_part_too_large_to_read_is_not_waved_through(tmp_path, monkeypatch):
    from sextant.refs import convert

    monkeypatch.setattr(convert, "_MAX_PART", 100)
    docx = _zipped(tmp_path / "big.docx", {"word/_rels/document.xml.rels": "<Relationships>" + " " * 500
                                           + "</Relationships>"})

    assert convert._links_local_files(docx)


_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def test_a_3gpp_specification_is_not_refused_for_its_template_or_mail_artifacts(tmp_path):
    """3GPP .docx files name the editor's Word template on their own disk
    and carry cid: image references from mail. Neither brings anything in, and
    refusing them would refuse every such specification."""
    from sextant.refs import convert

    rels = ('<Relationships>'
            f'<Relationship Id="rId1" Type="{_REL}/attachedTemplate" '
            'Target="file:///C:\\\\Users\\\\Editor\\\\AppData\\\\Roaming\\\\Microsoft\\\\Templates\\\\3gpp_70.dot" '
            'TargetMode="External"/>'
            f'<Relationship Id="rId2" Type="{_REL}/image" Target="cid:image001.png@01D5F28A.796839E0" '
            'TargetMode="External"/>'
            f'<Relationship Id="rId3" Type="{_REL}/hyperlink" Target="http://portal.3gpp.org/x" '
            'TargetMode="External"/></Relationships>')
    docx = _zipped(tmp_path / "23501-i40.docx", {"word/_rels/settings.xml.rels": rels})

    assert not convert._links_local_files(docx)


@pytest.mark.parametrize("kind", ["image", "oleObject", "subDocument", "aFChunk", "frame", "package"])
def test_a_relationship_that_brings_a_file_in_is_caught(tmp_path, kind):
    from sextant.refs import convert

    rels = (f'<Relationships><Relationship Id="r" Type="{_REL}/{kind}" '
            'Target="file:///home/u/secret" TargetMode="External"/></Relationships>')

    assert convert._links_local_files(_zipped(tmp_path / "x.docx", {"word/_rels/document.xml.rels": rels}))
