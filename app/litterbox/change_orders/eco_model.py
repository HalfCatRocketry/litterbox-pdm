"""
eco_model.py - what an engineering change order (ECO) holds, and how it is written as YAML and read back.
"""

import re
from dataclasses import dataclass, field

from litterbox.errors import LitterboxError

OPEN, RELEASED, REJECTED, WITHDRAWN = "open", "released", "rejected", "withdrawn"
STATUSES = (OPEN, RELEASED, REJECTED, WITHDRAWN)
CLOSED = (RELEASED, REJECTED, WITHDRAWN)         # a closed ECO is never changed again
STATUS_LABEL = {OPEN: "Open", RELEASED: "Released", REJECTED: "Rejected", WITHDRAWN: "Withdrawn"}

PREFIX = "ECO-"
DIGITS = 4
NUMBER_PATTERN = re.compile(rf"^{PREFIX}(\d{{{DIGITS},}})$")
MAX_NAME = 100
MAX_DESCRIPTION = 4000


class EcoError(LitterboxError):
    """An ECO is wrong, or a change to it isn't allowed. The message is safe to show."""


def number_text(number):
    """3 -> 'ECO-0003'."""
    return f"{PREFIX}{number:0{DIGITS}d}"


def number_value(text):
    """'ECO-0003' -> 3, or None if it isn't an ECO number."""
    match = NUMBER_PATTERN.match(str(text or ""))
    return int(match.group(1)) if match else None


def clean_name(text):
    name = " ".join(str(text or "").split())
    if not name:
        raise EcoError("The ECO needs a title.")
    if len(name) > MAX_NAME:
        raise EcoError(f"The ECO's title can be up to {MAX_NAME} characters.")
    return name


def clean_description(text):
    description = str(text or "").strip()
    if len(description) > MAX_DESCRIPTION:
        raise EcoError(f"The ECO's description can be up to {MAX_DESCRIPTION} characters.")
    return description


ECO_FIELDS = {"number", "name", "description", "status", "action", "template_name", "request_id", "parts",
              "requested_by", "requested_by_id", "requested_at", "signoffs", "history"}


@dataclass
class Eco:
    number: str                         # ECO-0001
    name: str                           # its title (the field keeps its first name, so older files still read)
    description: str = ""
    status: str = OPEN
    action: str = ""                    # what the workflow does: release, reopen, void, make_cots
    template_name: str = ""
    request_id: str = ""                # the workflow request it belongs to
    parts: list = field(default_factory=list)       # [{"pn": "HCR-00042-001", "revision": "A"}]
    requested_by: str = ""
    requested_at: str = ""
    signoffs: list = field(default_factory=list)    # copied from the request when the ECO is closed
    history: list = field(default_factory=list)     # [{"event", "by", "at", ...}]
    extra: dict = field(default_factory=dict)       # fields a newer Litterbox wrote, kept so nothing is lost
    requested_by_id: str = ""                       # the requester's id on the team list ("" before 0.4.2)

    @property
    def closed(self):
        return self.status in CLOSED

    def to_dict(self):
        data = {"number": self.number, "name": self.name, "description": self.description, "status": self.status,
                "action": self.action, "template_name": self.template_name, "request_id": self.request_id,
                "parts": [dict(p) for p in self.parts], "requested_by": self.requested_by}
        if self.requested_by_id:
            data["requested_by_id"] = self.requested_by_id
        data["requested_at"] = self.requested_at
        if self.signoffs:
            data["signoffs"] = [dict(s) for s in self.signoffs]
        data["history"] = [dict(h) for h in self.history]
        data.update({k: v for k, v in self.extra.items() if k not in data})
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise EcoError("An ECO file should hold an ECO's fields.")
        number = str(data.get("number", ""))
        if number_value(number) is None:
            raise EcoError(f"'{number}' is not an ECO number (like {number_text(1)}).")
        status = str(data.get("status", OPEN))
        if status not in STATUSES:
            raise EcoError(f"{number}: '{status}' is not an ECO status ({', '.join(STATUSES)}).")
        parts = data.get("parts") or []
        if not isinstance(parts, list) or not all(isinstance(p, dict) and p.get("pn") for p in parts):
            raise EcoError(f"{number}: 'parts' must list the parts it changes.")
        return cls(number, str(data.get("name", "")), str(data.get("description", "") or ""), status,
                   str(data.get("action", "")), str(data.get("template_name", "")), str(data.get("request_id", "")),
                   [dict(p, pn=str(p["pn"]), revision=str(p.get("revision", ""))) for p in parts],
                   str(data.get("requested_by", "")), str(data.get("requested_at", "")),
                   list(data.get("signoffs") or []), list(data.get("history") or []),
                   {k: v for k, v in data.items() if k not in ECO_FIELDS}, str(data.get("requested_by_id", "") or ""))
