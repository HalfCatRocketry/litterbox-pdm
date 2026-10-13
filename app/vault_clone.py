"""
vault_clone.py - Add org...: copy a vault that already exists on the Git host onto this computer.

The user pastes the repository's URL (the one the host's Clone button gives, like
https://dev.azure.com/team/project/_git/hcr-litterbox). It is cloned into a folder named after the repository, inside
Litterbox's own folder (C:\\Litterbox\\hcr-litterbox), and Litterbox then reads the org code and numbering from the vault.

    name, problem = vault_clone.parse_url(url)
    vault_clone.clone(url, target)
"""

import os
import re
import subprocess
import urllib.parse
from pathlib import Path

import litterbox_engine as eng

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


def clone(url, target):
    """git clone url into target (made if needed). Never asks for a password on a console that is not there: a
    sign-in the host needs comes from the Git credential manager's own window. Raises LitterboxError."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    eng.LOG(f"> git clone {url} {target}")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(
            ["git", "clone", url, str(target)], cwd=str(target.parent), capture_output=True, text=True,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise eng.LitterboxError("Could not run 'git'. Is Git installed?") from None
    if result.returncode != 0:
        raise eng.LitterboxError(f"Could not clone {url}\n\n{(result.stderr or result.stdout).strip()}")
    return target
