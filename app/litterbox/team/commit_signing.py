"""
signing.py - optional signed commits, using SSH keys (the kind Git 2.34+ and Windows' built-in OpenSSH support).

WHY      A commit's author name is just text anyone can type. A signature proves the commit was made by
         someone holding a particular private key. The team file lists each person's public signing key(s);
         Litterbox writes them to .litterbox/allowed_signers, and Git checks every commit against that file.

PER USER "Enable signing" (see enable()) makes an ed25519 key with no passphrase in your .ssh folder, tells THIS
         vault's Git settings to sign every commit with it, and shows you the public key to give an Admin, who
         pastes it into your entry in the team file. Until then your commits are signed but "untrusted".

VAULT    config.yaml: require_signatures: true makes Litterbox refuse to upload commits that are not signed
         by a key on the team list (the pre-push check in people.py). Off by default.

Only the key's holder can sign, so keep the private key file private. A key without a passphrase is as safe
as the computer's login; use ssh-keygen yourself if you want one with a passphrase and point
user.signingkey at it.
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from litterbox.parts import engine as eng
from litterbox.errors import LitterboxError

KEY_NAME = "litterbox_signing_ed25519"
# Git's one-letter signature results (%G?)
GOOD, BAD, UNKNOWN_VALIDITY, EXPIRED, EXPIRED_KEY, REVOKED, MISSING_KEY, NONE = "G", "B", "U", "X", "Y", "R", "E", "N"


class SigningError(LitterboxError):
    """Signing could not be set up or checked."""


def ssh_keygen():
    """Path to ssh-keygen, or None if OpenSSH isn't installed."""
    found = shutil.which("ssh-keygen")
    if found:
        return found
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "OpenSSH" / "ssh-keygen.exe"
    return str(windows) if windows.is_file() else None


def default_key_path():
    return Path.home() / ".ssh" / KEY_NAME


@dataclass
class SigningStatus:
    enabled: bool
    key_path: str = ""
    public_key: str = ""
    problems: list = field(default_factory=list)


def _git_config(repo, key):
    try:
        return eng.run(["git", "config", "--get", key], repo, quiet=True).strip()
    except LitterboxError:
        return ""


def status(repo):
    """Whether commits in this vault are being signed on this computer, and with which key."""
    sign = _git_config(repo, "commit.gpgsign").lower() == "true"
    fmt = _git_config(repo, "gpg.format").lower()
    key = _git_config(repo, "user.signingkey")
    problems = []
    if sign and fmt != "ssh":
        problems.append("Git is set to sign with GPG, not an SSH key.")
    if sign and not key:
        problems.append("Git has no signing key set.")
    public = ""
    if key:
        pub_path = Path(key if key.endswith(".pub") else key + ".pub") if not key.startswith("ssh-") else None
        if pub_path is not None:
            try:
                public = pub_path.read_text(encoding="utf-8").strip()
            except OSError:
                problems.append(f"The key file {pub_path} can't be read.")
        else:
            public = key
    return SigningStatus(sign and fmt == "ssh" and bool(key), key, public, problems)


def create_key(key_path=None, comment="litterbox"):
    """Make a signing key (no passphrase) unless one already exists there. Returns the public key text."""
    key_path = Path(key_path or default_key_path())
    pub = key_path.with_name(key_path.name + ".pub")
    if key_path.exists() and pub.exists():
        return pub.read_text(encoding="utf-8").strip()
    tool = ssh_keygen()
    if tool is None:
        raise SigningError("OpenSSH (ssh-keygen) isn't installed on this computer. On Windows it's an optional "
                           "feature: Settings > Apps > Optional features > OpenSSH Client.")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([tool, "-t", "ed25519", "-N", "", "-C", comment, "-f", str(key_path)],
                            capture_output=True, text=True)
    if result.returncode != 0 or not pub.exists():
        raise SigningError(f"ssh-keygen failed:\n{(result.stderr or result.stdout).strip()}")
    return pub.read_text(encoding="utf-8").strip()


def enable(repo, key_path=None, comment=None):
    """Sign every commit in THIS vault with the key (made if needed). Returns the public key to give an Admin."""
    eng.validate_repo(repo)
    key_path = Path(key_path or default_key_path())
    public = create_key(key_path, comment or eng.get_user(repo))
    pub_path = key_path.with_name(key_path.name + ".pub")
    for key, value in (("gpg.format", "ssh"), ("user.signingkey", str(pub_path)), ("commit.gpgsign", "true")):
        eng.run(["git", "config", "--local", key, value], repo, quiet=True)
    return public


def disable(repo):
    eng.run(["git", "config", "--local", "commit.gpgsign", "false"], repo, quiet=True)


@dataclass
class CommitSignature:
    sha: str
    result: str                 # G good (signed by a key on the team list), N none, E unknown key, B bad, ...
    signer: str                 # the team-file id for a good signature
    subject: str

    @property
    def trusted(self):
        return self.result == GOOD

    @property
    def description(self):
        return {GOOD: f"signed by {self.signer}", NONE: "not signed", MISSING_KEY: "signed, but the key can't be checked",
                BAD: "bad signature", UNKNOWN_VALIDITY: "signed by a key not on the team list"}.get(
            self.result, "signature problem")


def verify(repo, rev_range, allowed_signers_path):
    """Check the signature of each commit in `rev_range` against an allowed_signers file.
    Returns a list of CommitSignature, newest first."""
    out = eng.run(["git", "-c", f"gpg.ssh.allowedSignersFile={allowed_signers_path}", "log",
                   "--format=%H%x1f%G?%x1f%GS%x1f%s", rev_range], repo, quiet=True)
    found = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            found.append(CommitSignature(parts[0], parts[1], parts[2], parts[3]))
    return found


def untrusted_unpushed(repo):
    """Unpushed commits not signed by a key on the vault's (latest) team list: [CommitSignature]."""
    try:
        text = eng.run(["git", "show", f"@{{u}}:{'.litterbox/allowed_signers'}"], repo, quiet=True)
    except LitterboxError:
        text = ""                                   # nobody has a key yet
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "allowed_signers"
        path.write_text(text + ("\n" if text and not text.endswith("\n") else ""), encoding="utf-8")
        signatures = verify(repo, "@{u}..HEAD", path)
    return [s for s in signatures if not s.trusted]
