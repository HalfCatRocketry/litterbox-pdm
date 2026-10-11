"""
updater.py - find, check and install a newer Litterbox.

How an update works
  1. Every release on GitHub carries three files: the installer (Litterbox-Setup-X.Y.Z.exe), latest.json (which
     version it is, where the installer is, and the installer's SHA-256 fingerprint) and latest.json.sig (a
     signature on latest.json made with a private key only the maintainer holds).
  2. This program has the matching PUBLIC key built in (build_info.py). It downloads latest.json and the
     signature, and ignores the release unless the signature is right. So even someone who got into the GitHub
     account could not push a fake update without the private key.
  3. If the signed version is newer, the person is asked. On yes, the installer is downloaded, its fingerprint is
     checked against the signed one, and it is started quietly; Litterbox closes, the installer replaces the
     program files and starts Litterbox again. Settings, logs and the vault are never touched.

Nothing here runs in a development copy (see version.is_installed_build). Network errors are never fatal.
"""

import base64
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import version

MANIFEST_NAME = "latest.json"
SIGNATURE_NAME = "latest.json.sig"
MANIFEST_SCHEMA = 1
MAX_MANIFEST_BYTES = 200_000
TIMEOUT_SECONDS = 10
CHUNK = 256 * 1024
INSTALLER_NAME = re.compile(r"^[A-Za-z0-9._-]+\.exe$")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
REPO_NAME = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class UpdateError(Exception):
    """Something went wrong with an update. The message is plain English, safe to show."""


@dataclass
class Update:
    version: str
    notes: str
    name: str
    url: str
    sha256: str
    size: int


# ---------------------------------------------------------------------------
# Signing (used by the release pipeline to sign, and here to check)
# ---------------------------------------------------------------------------

def _ed25519():
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return ed25519


def generate_keypair():
    """(private_key, public_key), both base64 text. Keep the private one secret; the public one is not secret."""
    from cryptography.hazmat.primitives import serialization
    key = _ed25519().Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
    return base64.b64encode(private).decode(), public_from_private(base64.b64encode(private).decode())


def public_from_private(private_b64):
    from cryptography.hazmat.primitives import serialization
    key = _ed25519().Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(public).decode()


def sign(data, private_b64):
    """Signature (base64 text) on exactly these bytes."""
    key = _ed25519().Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    return base64.b64encode(key.sign(data)).decode()


def signature_is_good(data, signature_b64, public_b64):
    try:
        key = _ed25519().Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64))
        key.verify(base64.b64decode(signature_b64.strip()), data)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Reading the release information
# ---------------------------------------------------------------------------

def configured(repo=None, public_key=None):
    """Does this build know where to look for updates and which key to trust? (Development copies don't.)"""
    if repo is None or public_key is None:
        import build_info
        repo = build_info.REPO if repo is None else repo
        public_key = build_info.PUBLIC_KEY if public_key is None else public_key
    return bool(REPO_NAME.match(repo or "")) and bool(public_key)


def release_url(repo, filename):
    """Where the newest release's file of this name can be downloaded."""
    return f"https://github.com/{repo}/releases/latest/download/{filename}"


def parse_manifest(raw, signature_b64, public_key, repo):
    """Check latest.json (the exact bytes) against its signature and return an Update. Raises UpdateError."""
    if not signature_is_good(raw, signature_b64, public_key):
        raise UpdateError("The update information is not signed with the right key, so it was ignored.")
    try:
        data = json.loads(raw.decode("utf-8"))
        schema = data.get("schema")
        if schema != MANIFEST_SCHEMA:
            raise UpdateError("The newest release is in a newer format than this Litterbox can read. "
                              f"Download the installer from https://github.com/{repo}/releases instead.")
        installer = data["installer"]
        update = Update(version=str(data["version"]).lstrip("vV"), notes=str(data.get("notes", "")).strip(),
                        name=str(installer["name"]), url=str(installer["url"]),
                        sha256=str(installer["sha256"]).lower(), size=int(installer["size"]))
        version.parse(update.version)
    except UpdateError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
        raise UpdateError("The update information could not be understood.") from None
    if not INSTALLER_NAME.match(update.name):
        raise UpdateError("The update has an unexpected file name, so it was ignored.")
    if not SHA256.match(update.sha256) or update.size <= 0:
        raise UpdateError("The update information is incomplete, so it was ignored.")
    if not update.url.startswith(f"https://github.com/{repo}/releases/download/"):
        raise UpdateError("The update points somewhere other than this project's releases, so it was ignored.")
    return update


def http_get(url, limit=MAX_MANIFEST_BYTES):
    """Download a small file into memory. Raises UpdateError when offline or the file is too big."""
    request = urllib.request.Request(url, headers={"User-Agent": f"Litterbox/{version.VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"GitHub answered {e.code} for {url}" + (
            " (no release with that file was found; is the repository public and the release published?)"
            if e.code == 404 else "")) from None
    except Exception as e:
        raise UpdateError(f"Could not reach GitHub to check for updates ({type(e).__name__}).") from None
    if len(data) > limit:
        raise UpdateError("The update information was unexpectedly large, so it was ignored.")
    return data


def find_update(repo=None, public_key=None, current=None, fetch=None):
    """The newest release if it is newer than this program, else None. Raises UpdateError on any problem."""
    if repo is None or public_key is None:
        import build_info
        repo = build_info.REPO if repo is None else repo
        public_key = build_info.PUBLIC_KEY if public_key is None else public_key
    if not configured(repo, public_key):
        raise UpdateError("This copy of Litterbox is not set up to check for updates.")
    fetch = fetch or http_get
    raw = fetch(release_url(repo, MANIFEST_NAME))
    signature = fetch(release_url(repo, SIGNATURE_NAME)).decode("ascii", errors="replace")
    update = parse_manifest(raw, signature, public_key, repo)
    return update if version.is_newer(update.version, current) else None


# ---------------------------------------------------------------------------
# Getting and starting the installer
# ---------------------------------------------------------------------------

def update_folder():
    return Path(tempfile.gettempdir()) / "litterbox-update"


def stream_to_file(url, destination, progress=None):
    """Download a big file to disk. Returns (bytes written, sha256 hex)."""
    request = urllib.request.Request(url, headers={"User-Agent": f"Litterbox/{version.VERSION}"})
    digest, written = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS * 3) as response, open(destination, "wb") as out:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                if progress:
                    progress(written)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"The update could not be downloaded: GitHub answered {e.code} for {url}.") from None
    except Exception as e:
        raise UpdateError(f"The update could not be downloaded ({type(e).__name__}). Try again later.") from None
    return written, digest.hexdigest()


def download(update, folder=None, stream=stream_to_file, progress=None):
    """Download the installer and check it is exactly what the signed release information says. Returns its path."""
    folder = Path(folder) if folder else update_folder()
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.exe"):                       # earlier downloads
        try:
            old.unlink()
        except OSError:
            pass
    path = folder / update.name
    written, digest = stream(update.url, path, progress)
    if written != update.size or digest != update.sha256:
        try:
            path.unlink()
        except OSError:
            pass
        raise UpdateError("The downloaded update did not match its fingerprint, so it was deleted and not installed.")
    return path


def installer_command(path):
    """/SILENT shows a small progress window but asks nothing; the installer closes Litterbox if it is still
    running and starts it again when it finishes."""
    return [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]


def launch_installer(path, popen=subprocess.Popen):
    """Start the installer on its own, so it keeps going after Litterbox closes."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    try:
        popen(installer_command(path), creationflags=flags, close_fds=True)
    except OSError as e:
        raise UpdateError(f"The installer could not be started: {e}") from None