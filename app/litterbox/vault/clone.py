"""
clone.py - Add org... and Create new vault...: copy a repository on the Git host onto this computer (a vault that
already exists, or the empty repository a new vault starts as).

The user pastes the repository's URL (the one the host's Clone button gives, like
https://dev.azure.com/team/project/_git/hcr-litterbox). It is cloned into a folder named after the repository, inside
Litterbox's own folder (C:\\Litterbox\\hcr-litterbox), and Litterbox then reads the org code and numbering from the vault.

    name, problem = vault_clone.parse_url(url)
    vault_clone.clone(url, target)
    vault_clone.clone_or_reuse(url, target)      (Create new vault: an earlier try's copy is used again)
"""

import os
import re
import subprocess
import urllib.parse
from pathlib import Path

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download

SCHEMES = ("https://", "http://", "ssh://", "git://", "file://")


def parse_url(text):
    """(folder name, "") for a repository URL, or ("", what is wrong with it)."""
    url = (text or "").strip()
    if not url:
        return "", "Paste the repository's URL."
    scp_like = re.match(r"^[\w.-]+@[\w.-]+:[^\s]+$", url)                  # git@host:team/repo.git
    if not (url.lower().startswith(SCHEMES) or scp_like):
        return "", ("That doesn't look like a repository URL. On your Git host, press Clone and copy the https "
                    "address (it starts with https://).")
    if re.search(r"\s", url):
        return "", "A URL has no spaces in it."
    path = re.split(r"[?#]", url, maxsplit=1)[0].rstrip("/")
    last = re.split(r"[/:]", path)[-1]
    if last.lower().endswith(".git"):
        last = last[:-4]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", urllib.parse.unquote(last)).strip(" .")
    if not name or "://" in last or name in ("_git",):
        return "", "I can't tell the repository's name from that URL. Copy it again from the Clone button."
    return name, ""


def target_folder(root, name):
    return Path(root) / name


def clone(url, target, on_demand=True):
    """git clone url into target (made if needed). Never asks for a password on a console that is not there: a
    sign-in the host needs comes from the Git credential manager's own window. Raises LitterboxError.

    on_demand=True (download on demand): the CAD files are not downloaded, and the new copy keeps it that way until
    a file is used (see parts/downloads.py)."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    diagnostics.LOG(f"> git clone {url} {target}")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if on_demand:
        env["GIT_LFS_SKIP_SMUDGE"] = "1"                # leave the CAD files as pointers
    try:
        result = subprocess.run(
            ["git", "clone", url, str(target)], cwd=str(target.parent), capture_output=True, text=True,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise LitterboxError("Could not run 'git'. Is Git installed?") from None
    if result.returncode != 0:
        raise LitterboxError(f"Could not clone {url}\n\n{(result.stderr or result.stdout).strip()}")
    if on_demand:
        lfs_download.set_on_demand(target, True)
    return target


def origin_url(folder):
    """The URL `folder` was cloned from, or "" if it isn't a clone."""
    try:
        result = subprocess.run(["git", "-C", str(folder), "remote", "get-url", "origin"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def clone_or_reuse(url, target, on_demand=True):
    """Create new vault...: clone `url` into `target`, or use the copy an earlier try already cloned there (one that
    stopped part-way, for example because Git didn't know your email yet). Raises LitterboxError if `target` holds
    something else."""
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        if origin_url(target).rstrip("/") == url.strip().rstrip("/"):
            diagnostics.LOG(f"Using the copy cloned earlier: {target}")
            return target
        raise LitterboxError(f"{target} already exists and isn't a copy of {url.strip()}. Rename or remove it, "
                             "then try again.")
    return clone(url.strip(), target, on_demand)
