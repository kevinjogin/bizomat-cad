"""Static checks that keep the add-in, the installer and the website in step (they run on Linux; the MSI itself is built
and the add-in compiled against the SOLIDWORKS 2022 interop by solidworks.yml on Windows and Linux):

- the MSI registers the add-in class SOLIDWORKS loads (same CLSID and ProgID as the code), lists it in Tools > Add-Ins
  under the add-in's own title and description, and keeps the UpgradeCode so it upgrades KEVOS Bridge (up to 0.11) and
  CADOS for SOLIDWORKS (0.12.0 to 0.12.2) in place;
- what people read in Windows (the product, its publisher, the Start menu) says BIZOMAT, while every id stays;
- the MSI's file name, the stable download name and the server's download link agree (they keep the earlier name);
- the add-in's version can upgrade (higher than the last released 0.12.2);
- the logo the add-in and the Companion draw is the brand's own (the paths shared/brand/build.mjs generates);
- development signing (installer/sign-development.ps1, docs/BIZOMAT-DEV-SIGNING.md) signs every binary of BIZOMAT's own
  that the MSI holds, then the MSI, with SHA-256, and never exports a private key; the repository holds no private
  key; the original installer backup is byte for byte what was released."""
import hashlib
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
WXS = ROOT / "installer" / "KEVOS-Bridge.wxs"
ENTRY = (ROOT / "solidworks" / "src" / "Addin" / "Entry.cs").read_text()
NS = {"w": "http://wixtoolset.org/schemas/v4/wxs"}


def _const(name):
    return re.search(rf'public const string {name} = "([^"]*)";', ENTRY).group(1)


def test_msi_registers_the_add_in_solidworks_loads():
    tree = ET.parse(WXS).getroot()
    clsid = _const("ClassId")
    keys = {k.get("Key"): k for k in tree.iter("{%s}RegistryKey" % NS["w"])}
    addin = keys[r"SOFTWARE\SolidWorks\Addins\{" + clsid + "}"]
    vals = {v.get("Name"): v.get("Value") for v in addin.iter("{%s}RegistryValue" % NS["w"])}
    assert vals["Title"] == _const("Title") == "BIZOMAT CAD"
    assert vals["Description"] == _const("Description") and vals["Description"].startswith("BIZOMAT CAD:")
    assert vals[None] == "1"  # listed for every SOLIDWORKS version installed
    # the COM class SOLIDWORKS creates: CLSID -> InprocServer32 (mscoree) with the class, assembly and code base
    text = WXS.read_text()
    assert ("CLSID\\{" + clsid + "}") in text and 'Value="OpenSketch.Sw.SwAddin"' in text and _const("ProgIdName") == "OpenSketch.Sw.SwAddin"
    assert 'Name="CodeBase" Type="string" Value="file:///[#AddinDll]"' in text and "mscoree.dll" in text.lower()


def test_msi_is_bizomat_cad_and_upgrades_every_earlier_version():
    root = ET.parse(WXS).getroot()
    pkg = root.find("w:Package", NS)
    assert pkg.get("Name") == "BIZOMAT CAD for SOLIDWORKS" and pkg.get("Manufacturer") == "BIZOMAT"
    assert pkg.get("UpgradeCode") == "cef90528-e91b-42ae-9556-f70a612cb58f"  # never change: upgrades depend on it
    assert pkg.get("Scope") == "perMachine"
    assert "KEVOS Bridge" not in re.sub(r"<!--.*?-->", "", WXS.read_text(), flags=re.S)
    # everything people read: the product, publisher, messages, Apps entry, Start menu folder and shortcuts
    shown = [pkg.get("Name"), pkg.get("Manufacturer")]
    for tag, attrs in (("SummaryInformation", ("Description", "Manufacturer")), ("MajorUpgrade", ("DowngradeErrorMessage",)),
                       ("Launch", ("Message",)), ("Feature", ("Title",)), ("Shortcut", ("Name", "Description"))):
        shown += [e.get(a) for e in root.iter("{%s}%s" % (NS["w"], tag)) for a in attrs if e.get(a)]
    props = {p.get("Id"): p.get("Value") for p in root.iter("{%s}Property" % NS["w"])}
    shown += [props["ARPCOMMENTS"], props["ARPURLINFOABOUT"]]
    menu = next(d for d in root.iter("{%s}Directory" % NS["w"]) if d.get("Id") == "KevosMenu")
    shown.append(menu.get("Name"))
    assert menu.get("Name") == "BIZOMAT" and props["ARPURLINFOABOUT"] == "https://bizomat.ai/"
    for text in shown:
        assert "CADOS" not in text and "KEVOS" not in text and "kevos.com" not in text, text
    names = {s.get("Id"): s.get("Name") for s in root.iter("{%s}Shortcut" % NS["w"])}
    assert names == {"StartCompanion": "BIZOMAT Companion", "PairComputer": "Pair this computer with BIZOMAT CAD",
                     "Diagnostics": "BIZOMAT CAD diagnostics", "Unpair": "Remove this computer from BIZOMAT CAD"}
    for text in shown:
        assert "OpenSketch" not in text, text


def test_the_ids_existing_installs_depend_on_are_unchanged():
    """The install folder, the registry keys, the Companion's Run value and its file name: an upgrade finds them."""
    text = WXS.read_text()
    platform = (ROOT / "solidworks" / "src" / "Companion" / "Platform.cs").read_text()
    run = re.search(r'const string RunName = "([^"]+)";', platform).group(1)
    assert run == "KEVOS Companion" and f'CurrentVersion\\Run" Name="{run}"' in text
    assert '<Directory Id="KevosDir" Name="KEVOS">' in text and '<Directory Id="INSTALLFOLDER" Name="Bridge" />' in text
    assert 'Key="SOFTWARE\\KEVOS\\Bridge"' in text and 'Source="$(var.Source)/KEVOS.Companion.exe"' in text
    assert 'Source="$(var.Source)/OpenSketch.Sw.dll"' in text and "{275256ff-b73a-4e4f-9ea8-842b6626d471}" in text
    assert re.search(r'public const string PipeName\(|PipeName\(string userSid\) => "KEVOS\.Bridge\."',
                     (ROOT / "solidworks" / "src" / "Core" / "Bridge2" / "Wire.cs").read_text())


def test_version_can_upgrade():
    props = (ROOT / "solidworks" / "Directory.Build.props").read_text()
    v = re.search(r"<Version>([\d.]+)</Version>", props).group(1)
    assert tuple(map(int, v.split("."))) > (0, 12, 3)  # the last CADOS for SOLIDWORKS release (KEVOS Bridge up to 0.11)
    assert "<Company>BIZOMAT</Company>" in props and "<Product>BIZOMAT CAD for SOLIDWORKS</Product>" in props
    # the server still asks only for the versions each feature needs
    from opensketch import swbridge
    assert swbridge.version_tuple(v) >= (0, 10, 0)


def test_the_add_in_draws_the_brands_own_logo():
    from opensketch import bizomat_brand as bz
    art = (ROOT / "solidworks" / "src" / "Core" / "BrandArt.cs").read_text()
    for name, want in (("WordmarkPath", bz.WORDMARK_PATH), ("BPath", bz.B_PATH), ("BarPath", bz.BAR_PATH)):
        assert re.search(rf'public const string {name} = "([^"]+)";', art).group(1) == want, name
    _, _, width, height = bz.WORDMARK_VIEWBOX.split()
    assert f"WordmarkWidth = {width}f, Height = {height}f, BWidth = {bz.B_VIEWBOX.split()[2]}f" in art
    # the B on the mark: half the tile tall, as shared/brand/build.mjs places it (scale 512 * 0.5 / 240)
    assert "CapTop = 3f, Cap = 240f, MarkBHeight = 0.5f" in art and "scale(1.06667)" in bz.MARK_TRANSFORM


def test_download_names_agree(tmp_path, monkeypatch):
    build = (ROOT / "installer" / "build.ps1").read_text()
    assert '"BIZOMAT-CAD-Automation-$Version-x64"' in build and "'BIZOMAT-CAD-Automation-x64.msi'" in build
    assert "'CADOS-for-SOLIDWORKS-x64.msi'" in build, "the 0.12 stable name stays published for links already given out"
    monkeypatch.setenv("OPENSKETCH_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("OPENSKETCH_INSTALLER_URL", raising=False)
    from opensketch import server
    r = TestClient(server.app).get("/download/solidworks", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://bizomat.ai/downloads/cad/BIZOMAT-CAD-Automation-x64.msi"
    assert 'msi_url = "https://bizomat.ai/downloads/cad/$name"' in build, "the release record points where publish puts the file"
    # a release the operator published wins
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "bridge-release.json").write_text(
        '{"version": "0.13.0", "msi_url": "https://example.com/BIZOMAT-CAD-Automation-0.13.0-x64.msi", "sha256": "sha256:00"}')
    assert TestClient(server.app).get("/download/solidworks", follow_redirects=False).headers["location"] == \
        "https://example.com/BIZOMAT-CAD-Automation-0.13.0-x64.msi"


def test_the_download_needs_sign_in(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENSKETCH_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("OPENSKETCH_PASSWORD", "server-secret")
    from opensketch import accounts, server
    accounts.create_owner("owner@example.com", "Owner", "owner-pass-1")
    accounts.create_member("pat@example.com", "Pat", "given-pass-1")
    anon = TestClient(server.app)
    r = anon.get("/download/solidworks", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/download/solidworks"
    assert anon.post("/login", data={"email": "pat@example.com", "password": "given-pass-1", "next": "/download/solidworks"},
                     follow_redirects=False).headers["location"] == "/download/solidworks"
    r = anon.get("/download/solidworks", follow_redirects=False)
    assert r.status_code == 302 and "BIZOMAT-CAD-Automation" in r.headers["location"]


def test_the_bizomat_icons_ship():
    """The BIZOMAT mark: in the programs (Start menu, Apps list, taskbar, Explorer) and next to the add-in in Tools > Add-Ins."""
    import struct
    ico = (ROOT / "solidworks" / "src" / "Shared" / "bizomat.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, kind) == (0, 1)
    sizes = {(ico[6 + 16 * i] or 256) for i in range(count)}
    assert {16, 24, 32, 48, 256} <= sizes, sizes
    for proj in ("Companion/KEVOS.Companion.csproj", "App/OpenSketch.Sw.App.csproj"):
        assert "<ApplicationIcon>../Shared/bizomat.ico</ApplicationIcon>" in (ROOT / "solidworks" / "src" / proj).read_text(), proj
    bmp = (ROOT / "solidworks" / "package" / "BIZOMAT.bmp").read_bytes()
    assert bmp[:2] == b"BM" and struct.unpack("<ii", bmp[18:26]) == (16, 16)
    assert "package/BIZOMAT.bmp" in (ROOT / "solidworks" / "build.sh").read_text()
    root = ET.parse(WXS).getroot()
    files = {f.get("Id"): f.get("Source") for f in root.iter("{%s}File" % NS["w"])}
    assert files["AddinIcon"] == "$(var.Source)/BIZOMAT.bmp"
    keys = {k.get("Key"): k for k in root.iter("{%s}RegistryKey" % NS["w"])}
    addin = keys[r"SOFTWARE\SolidWorks\Addins\{" + _const("ClassId") + "}"]
    vals = {v.get("Name"): v.get("Value") for v in addin.iter("{%s}RegistryValue" % NS["w"])}
    assert vals["Icon Path"] == "[#AddinIcon]"
    # the admin and per-user registrations set it too, when the bitmap is next to the add-in
    assert 'k.SetValue("Icon Path", icon)' in (ROOT / "solidworks" / "src" / "Addin" / "Entry.cs").read_text()
    assert (ROOT / "solidworks" / "src" / "App" / "Program.cs").read_text().count('k.SetValue("Icon Path", icon)') == 2


SIGN_DEV = ROOT / "installer" / "sign-development.ps1"


def test_development_signing_signs_every_own_binary_in_the_msi():
    sign = SIGN_DEV.read_text()
    build = (ROOT / "installer" / "build.ps1").read_text()
    own = re.search(r"\$OwnFiles = @\(([^)]*)\)", sign).group(1)
    own = set(re.findall(r"'([^']+)'", own))
    sources = {Path(f.get("Source")).name for f in ET.parse(WXS).getroot().iterfind(".//w:File", NS)}
    binaries = {n for n in sources if n.lower().endswith((".dll", ".exe"))}
    assert own == binaries, "every DLL and EXE the MSI installs is signed and checked (they are all BIZOMAT's own)"
    signed_by_build = set(re.findall(r"'([^']+\.(?:dll|exe))'", re.search(r"foreach \(\$f in ([^)]*)\) \{ Sign", build).group(1)))
    assert signed_by_build == binaries, "build.ps1 signs the same files before packaging"
    # SHA-256 digests, RFC 3161 SHA-256 timestamps, and a store certificate chosen by thumbprint
    assert "sign /fd sha256 @stamp @by" in build and "@('/tr', $Timestamp, '/td', 'sha256')" in build
    assert "@('/sha1', $CertThumbprint)" in build
    assert "never fall back to an unsigned build" in build
    # checks after signing: signtool verify with the default Authenticode policy, Windows' own check, the MSI's contents
    assert "verify /pa /v" in sign and "Get-AuthenticodeSignature" in sign and "msiexec.exe -ArgumentList '/a'" in sign
    assert "exit 1" in sign and "exit 0" in sign


def test_development_signing_never_exports_a_private_key():
    sign = SIGN_DEV.read_text()
    assert "-KeyExportPolicy NonExportable" in sign
    assert "-Type CodeSigningCert" in sign and "-HashAlgorithm SHA256" in sign and "-KeyLength 3072" in sign
    assert "Cert:\\CurrentUser\\My" in sign
    for bad in ("Export-PfxCertificate", "-Type PFX", ".pfx", "ToByteArray", "Export(", ".PrivateKey"):
        assert bad not in sign, bad
    # the only export is the public certificate (DER)
    assert re.findall(r"Export-Certificate [^\n]*", sign) == ["Export-Certificate -Cert $cert -FilePath $cerFile -Type CERT | Out-Null"]
    # trust is added for this Windows user on this computer only
    assert "Cert:\\CurrentUser\\Root" in sign and "LocalMachine\\Root | Out-Null" not in sign
    assert all(ord(c) < 128 for c in sign), "Windows PowerShell 5.1 reads a file without a BOM as ANSI"


def test_the_repository_holds_no_private_key():
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert not [f for f in files if f.lower().endswith((".pfx", ".p12", ".pvk", ".snk"))]
    ignore = (ROOT / ".gitignore").read_text().split()
    assert {"*.pfx", "*.p12", "*.pvk", "installer/out/"} <= set(ignore)
    for f in files:
        if f.startswith(("backups/", "installer/")) and (ROOT / f).is_file():
            data = (ROOT / f).read_bytes()
            assert b"PRIVATE KEY" not in data, f


def test_the_original_installer_backup_is_what_was_released():
    import pytest
    if not (ROOT / "backups" / "installer").is_dir():
        pytest.skip("the installer backups stay in jogkev-creator/CADOS (backups/installer); this repository does not copy them")
    found = sorted((ROOT / "backups" / "installer" / "original").glob("*/*.msi"))
    assert found, "the original installer is backed up"
    for msi in found:
        line = (msi.parent / (msi.name + ".sha256")).read_text("utf-8-sig").split()
        digest = hashlib.sha256(msi.read_bytes()).hexdigest()
        assert line == [digest, msi.name]
        assert digest in (msi.parent / "MANIFEST.md").read_text()
    assert "backups/** -text" in (ROOT / ".gitattributes").read_text(), "no line-ending conversion of backups"


def test_the_server_serves_an_installer_put_in_its_data_folder(tmp_path, monkeypatch):
    """While bizomat.ai serves no /downloads/ (the website on Fly has no such route), the operator puts the MSI on the
    CAD server's volume and the Download button gives it from there, to signed-in people only, with its SHA-256."""
    data = tmp_path / "data"
    monkeypatch.setenv("OPENSKETCH_DATA", str(data))
    for k in ("OPENSKETCH_INSTALLER_URL", "OPENSKETCH_PASSWORD", "OPENSKETCH_PUBLIC_URL", "OPENSKETCH_REDIRECT_HOSTS"):
        monkeypatch.delenv(k, raising=False)
    from opensketch import accounts, server
    accounts.create_owner("owner@example.com", "Owner", "owner-pass-1")
    accounts.create_member("pat@example.com", "Pat", "given-pass-1")
    anon = TestClient(server.app)
    # no file yet: the published addresses
    assert anon.post("/login", data={"email": "pat@example.com", "password": "given-pass-1", "next": "/"},
                     follow_redirects=False).status_code == 303
    r = anon.get("/download/solidworks", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://bizomat.ai/downloads/cad/BIZOMAT-CAD-Automation-x64.msi"
    r = anon.get("/download/solidworks.sha256", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://bizomat.ai/downloads/cad/BIZOMAT-CAD-Automation-x64.msi.sha256"
    # the file on the volume
    msi = bytes(range(256)) * 5000  # binary, not text: nothing may rewrite or decode it
    (data / "downloads").mkdir(parents=True)
    (data / "downloads" / "BIZOMAT-CAD-Automation-x64.msi").write_bytes(msi)
    digest = hashlib.sha256(msi).hexdigest()
    r = anon.get("/download/solidworks", follow_redirects=False)
    assert r.status_code == 200 and r.content == msi
    assert r.headers["content-type"] == "application/x-msi" and r.headers["x-content-sha256"] == digest
    assert 'filename="BIZOMAT-CAD-Automation-x64.msi"' in r.headers["content-disposition"]
    r = anon.get("/download/solidworks.sha256", follow_redirects=False)
    assert r.status_code == 200 and r.text == f"{digest}  BIZOMAT-CAD-Automation-x64.msi\n"
    # still only for people who are signed in
    for path in ("/download/solidworks", "/download/solidworks.sha256"):
        r = TestClient(server.app).get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    # an address the operator set wins over the file
    monkeypatch.setenv("OPENSKETCH_INSTALLER_URL", "https://example.com/x.msi")
    assert anon.get("/download/solidworks", follow_redirects=False).headers["location"] == "https://example.com/x.msi"


def test_the_installer_on_the_volume_is_served_whole_under_cad(tmp_path, monkeypatch):
    """At https://bizomat.ai/cad (the prefix is taken off and HTML is rewritten) the MSI comes through byte for byte."""
    data = tmp_path / "data"
    monkeypatch.setenv("OPENSKETCH_DATA", str(data))
    for k in ("OPENSKETCH_INSTALLER_URL", "OPENSKETCH_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENSKETCH_PUBLIC_URL", "https://bizomat.ai/cad")
    from opensketch import accounts, server
    accounts.create_owner("owner@example.com", "Owner", "owner-pass-1")
    msi = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b'<a href="/x">' + bytes(range(256)) * 100
    (data / "downloads").mkdir(parents=True)
    (data / "downloads" / "BIZOMAT-CAD-Automation-x64.msi").write_bytes(msi)
    c = TestClient(server.app, base_url="https://bizomat.ai")
    assert c.post("/cad/login", data={"email": "owner@example.com", "password": "owner-pass-1", "next": "/"},
                  headers={"host": "bizomat.ai"}, follow_redirects=False).status_code == 303
    r = c.get("/cad/download/solidworks", headers={"host": "bizomat.ai"}, follow_redirects=False)
    assert r.status_code == 200 and r.content == msi
    # the pages link the checksum this server answers for, under /cad
    page = c.get("/cad/docs", headers={"host": "bizomat.ai"}).text
    assert 'href="/cad/download/solidworks.sha256"' in page and "downloads/cad/BIZOMAT-CAD-Automation-x64.msi.sha256" not in page


def test_the_msi_never_touches_documents_so_uninstall_keeps_user_files():
    """Documents\\BIZOMAT CAD is made by the add-in for each Windows user, never by the MSI: an uninstall, a repair or an
    upgrade cannot remove or change anyone's files there (nor the old Documents\\OpenSketch folder)."""
    text = re.sub(r"<!--.*?-->", "", WXS.read_text(), flags=re.S)
    for word in ("PersonalFolder", "MyDocuments", "Documents", "OneDrive", "BIZOMAT CAD\\", "OpenSketch\\"):
        assert word not in text, word
    assert "RemoveFolderEx" not in text and "util:RemoveFolderEx" not in text


def test_no_code_makes_an_opensketch_folder():
    """Since 0.14 nothing creates a folder called OpenSketch (Documents, LocalAppData, Temp): the add-in and the manual
    installer use Documents\\BIZOMAT CAD (Core/UserFolders.cs), whose migration only reads the old folder."""
    src = ROOT / "solidworks" / "src"
    offenders = []
    for f in src.rglob("*.cs"):
        if "/bin/" in str(f) or "/obj/" in str(f):
            continue
        code = re.sub(r"//.*", "", f.read_text())
        if re.search(r'Path\.Combine\([^;]*SpecialFolder\.(MyDocuments|LocalApplicationData|Personal)[^;]*"OpenSketch"', code) or \
           re.search(r'Path\.Combine\([^;]*GetTempPath\(\)[^;]*"OpenSketch', code):
            offenders.append(f.relative_to(ROOT).as_posix())
    assert offenders == []
    folders = (src / "Core" / "UserFolders.cs").read_text()
    assert 'RootName = "BIZOMAT CAD"' in folders and "FDD39AD0-238F-46AF-ADB4-6C85480369C7" in folders  # FOLDERID_Documents
    assert "File.Delete(" not in folders.replace('File.Delete(temp)', '').replace('File.Delete(path)', ''), "the migration deletes nothing of the user's"
    assert "Directory.Delete" not in folders
