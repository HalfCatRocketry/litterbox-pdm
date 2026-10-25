"""
update_notices.py - notices.json, the maintainer's signed word on which update keys are no longer to be trusted and
where Litterbox's releases have moved (see user/updater.py for updates themselves, docs/RELEASING.md for making one).

    {"schema": 1, "revoked": ["<public key>", ...], "moved_to": "owner/name"}       both optional

The pipeline attaches packaging/notices.json and its signature to every release, so an installed copy reads them
with each update check, at releases/latest/download/. They count only when signed by a SPARE key
(updater.SPARE_PUBLIC_KEYS), which is kept offline and never given to GitHub: the key GitHub signs releases with
can't revoke a spare or send installed copies elsewhere, so someone who stole it couldn't lock the maintainer out.
packaging/sign_notice.py makes them, on the maintainer's own computer.

What a copy learns is kept in its settings (user/settings.py: revoked_update_keys, update_repo), so a revoked key
stays revoked even if the person never installs the update that came with it.
"""

import json
import re
from dataclasses import dataclass

NOTICES_NAME = "notices.json"
NOTICES_SIGNATURE_NAME = "notices.json.sig"
NOTICES_SCHEMA = 1
REPO_NAME = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class Notices:
    revoked: tuple = ()
    moved_to: str = ""


NONE = Notices()


class NoticeError(Exception):
    """notices.json couldn't be trusted or understood. The message is plain English."""


def build(revoked=(), moved_to=""):
    """notices.json's bytes. Raises NoticeError for a repository that isn't owner/name."""
    if moved_to and not REPO_NAME.match(moved_to):
        raise NoticeError(f"'{moved_to}' is not an owner/name repository.")
    data = {"schema": NOTICES_SCHEMA, "revoked": sorted(dict.fromkeys(revoked))}
    if moved_to:
        data["moved_to"] = moved_to
    return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def parse(raw, signature_b64, spare_keys, revoked=(), is_good=None):
    """Notices from notices.json's exact bytes, if a spare key that isn't revoked signed them. Raises NoticeError.
    `is_good(data, signature, key)` checks one signature (updater.signature_is_good)."""
    keys = [key for key in spare_keys if key not in set(revoked)]
    if not any(is_good(raw, signature_b64, key) for key in keys):
        raise NoticeError("The update notices are not signed with a spare key, so they were ignored.")
    try:
        data = json.loads(raw.decode("utf-8"))
        if data.get("schema") != NOTICES_SCHEMA:
            raise NoticeError("The update notices are in a newer format than this Litterbox can read.")
        found = data.get("revoked") or []
        moved_to = str(data.get("moved_to") or "")
        if not isinstance(found, list) or not all(isinstance(key, str) for key in found):
            raise NoticeError("The update notices could not be understood.")
    except NoticeError:
        raise
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
        raise NoticeError("The update notices could not be understood.") from None
    if moved_to and not REPO_NAME.match(moved_to):
        raise NoticeError("The update notices name a place that isn't a repository, so they were ignored.")
    return Notices(revoked=tuple(dict.fromkeys(found)), moved_to=moved_to)
