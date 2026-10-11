"""
gui_logic.py - the decisions the Litterbox window makes, with no window code in it.

Which parts a button may act on, how the list is filtered, what the summary line
says, how history is laid out. Keeping this separate from the window code means
all of it can be tested automatically.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from litterbox_engine import LitterboxError
import pn as pn_module
import registry

# ---------------------------------------------------------------------------
# The list: filtering
# ---------------------------------------------------------------------------

VIEWS = ("All", "Mine", "Checked out", "Released")


def filter_rows(rows, search="", view="All", show_void=False):
    """Pick which PartStatus rows to show.

    search      matches part number, name or description, ignoring capitals
    view        one of VIEWS
    show_void   void parts are hidden unless this is True
    """
    needle = (search or "").strip().lower()
    shown = []
    for row in rows:
        if row.kind == "void" and not show_void:
            continue
        if view == "Mine" and row.kind != "mine":
            continue
        if view == "Checked out" and row.kind not in ("mine", "theirs"):
            continue
        if view == "Released" and row.kind != "released" and not getattr(row, "released_revision", ""):
            continue
        if needle and not any(needle in text.lower() for text in
                              (str(row.pn), row.name, row.description, row.import_path)):
            continue
        shown.append(row)
    return shown


def _natural_key(text):
    """'HCR-10 b' sorts after 'HCR-9 b': numbers compare as numbers, words ignore capitals."""
    return [(0, int(piece), "") if piece.isdigit() else (1, 0, piece)
            for piece in re.split(r"(\d+)", text.lower()) if piece]


def sort_order(values, reverse=False):
    """Positions of `values` in sorted order. Blank values always come last."""
    texts = [str(value).strip() for value in values]
    filled = [i for i, text in enumerate(texts) if text]
    blank = [i for i, text in enumerate(texts) if not text]
    filled.sort(key=lambda i: _natural_key(texts[i]), reverse=reverse)
    return filled + blank


def file_types(files):
    """['cad/HCR-00001-001.SLDPRT', 'cad/HCR-00001-001.SLDDRW'] -> 'PRT, DRW'"""
    kinds = []
    for path in files:
        ext = PurePosixPath(path).suffix.lstrip(".").upper()
        if ext.startswith("SLD") and len(ext) > 3:
            ext = ext[3:]
        if ext and ext not in kinds:
            kinds.append(ext)
    return ", ".join(kinds)


# ---------------------------------------------------------------------------
# Buttons: what each action may be used on
# ---------------------------------------------------------------------------

# The "kind" values come from litterbox_engine.PartStatus.kind
ALLOWED_KINDS = {
    "checkout": {"ok", "unclaimed"},
    "checkin": {"mine"},
    "save": {"mine"},
    "undo": {"mine"},
    "edit": {"mine"},
    "open": {"ok", "mine", "theirs", "stray", "unclaimed", "released", "cots", "void", "pending"},    # anything downloaded
    "open_drawing": {"ok", "mine", "theirs", "stray", "unclaimed", "released", "cots", "void", "pending"},
    "release": {"ok", "pending"},            # on a pending part it completes an approved request (see the window)
    "make_cots": {"ok"},
    "revise": {"released"},
    "cancel_revision": {"ok", "mine"},
    "reopen": {"released", "cots"},
    "void": {"ok", "cots"},
    "references": {"ok", "mine", "theirs", "unclaimed", "stray", "released", "cots", "void", "missing", "pending"},
}

# These can be done to several parts at once; the rest need exactly one part selected.
MULTI = {"checkout", "checkin", "save", "undo"}

NAME = {            # "...cannot <name> ..."
    "checkout": "check out", "checkin": "check in", "save": "save progress on",
    "undo": "undo the checkout of", "edit": "edit the details of", "open": "open", "open_drawing": "open the drawing of", "release": "release", "make_cots": "make COTS", "revise": "revise", "cancel_revision": "cancel the revision of", "reopen": "reopen", "void": "void", "references": "show the references of",
}
PAST = {            # "<past> 2 parts"
    "checkout": "Checked out", "checkin": "Checked in", "save": "Saved progress on",
    "undo": "Undid checkout of", "edit": "Edited", "open": "Opened", "open_drawing": "Opened the drawing of", "release": "Released", "make_cots": "Made COTS", "revise": "Revised", "cancel_revision": "Cancelled the revision of", "reopen": "Reopened", "void": "Voided", "references": "Showed the references of",
}


@dataclass
class ActionPlan:
    targets: list = field(default_factory=list)     # part numbers the action will run on
    skipped: list = field(default_factory=list)     # [(pn, reason)] that were selected but can't be used
    message: str = ""                               # if not empty: show this and do nothing


def plan_action(action, selected, rows_by_pn):
    """Decide which of the selected parts an action applies to.

    `selected` is a list of PN objects; `rows_by_pn` maps PN -> PartStatus.
    """
    if not selected:
        return ActionPlan(message="Select a part first.")
    if action not in MULTI and len(selected) > 1:
        return ActionPlan(message=f"Select just one part to {NAME[action]}.")

    allowed = ALLOWED_KINDS[action]
    targets, skipped = [], []
    for pn in selected:
        row = rows_by_pn.get(pn)
        if row is not None and row.kind in allowed:
            targets.append(pn)
        else:
            skipped.append((pn, row.state if row is not None else "not in the list"))

    plan = ActionPlan(targets, skipped)
    if not targets:
        if len(skipped) == 1:
            pn, reason = skipped[0]
            plan.message = f"Can't {NAME[action]} {pn}: {reason}."
        else:
            plan.message = f"None of the selected parts can be used to {NAME[action]}."
    return plan


def run_batch(targets, func):
    """Run func(pn) for each part, carrying on if one fails.

    Returns (done, failed): done is [(pn, result)], failed is [(pn, error text)].
    """
    done, failed = [], []
    for pn in targets:
        try:
            done.append((pn, func(pn)))
        except LitterboxError as e:
            failed.append((pn, str(e)))
    return done, failed


def _parts(count):
    return f"{count} part" + ("" if count == 1 else "s")


def summary(action, done, failed=0, skipped=0):
    """One line saying what just happened, e.g. 'Checked out 2 parts, 1 failed'."""
    if done:
        text = f"{PAST[action]} {_parts(done)}"
        if failed:
            text += f", {failed} failed"
    else:
        text = f"Could not {NAME[action]} {_parts(failed or skipped or 1)}"
    if skipped and done:
        text += f", skipped {skipped}"
    return text


# ---------------------------------------------------------------------------
# Window icon
# ---------------------------------------------------------------------------

ICON_CHOICES = ("white", "black")
DEFAULT_ICON = "white"


def icon_filename(choice=DEFAULT_ICON):
    """'white' -> 'litterbox_icon_white.ico'. Anything unrecognized gives the default."""
    choice = str(choice or "").strip().lower()
    if choice not in ICON_CHOICES:
        choice = DEFAULT_ICON
    return f"litterbox_icon_{choice}.ico"


def find_icon(assets_dir, choice=DEFAULT_ICON):
    """The icon file to use, or None if there isn't one.

    Tries the chosen icon first, then the default white one, then the black one,
    so a missing file never stops the program from starting.
    """
    assets_dir = Path(assets_dir)
    wanted = [icon_filename(choice), icon_filename("white"), icon_filename("black")]
    for name in wanted:
        path = assets_dir / name
        if path.is_file():
            return path
    return None


# ---------------------------------------------------------------------------
# Check-in with nothing changed
# ---------------------------------------------------------------------------

def parts_without_changes(reports):
    """From [(pn, ChangeReport)], the parts with nothing to check in, as [(pn, [cad files])]."""
    return [(pn, list(report.unchanged_files)) for pn, report in reports if not report.has_changes]


def unchanged_lines(unchanged):
    """Lines for the 'No changes were detected in these files' window.

    `unchanged` is [(pn, [file paths])]. Each part is listed with its files under it.
    """
    lines = []
    for pn, files in unchanged:
        lines.append(str(pn))
        names = [PurePosixPath(f).name for f in files]
        if names:
            lines.extend("    " + name for name in names)
        else:
            lines.append("    (no CAD files yet)")
    return lines


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def cad_changes(paths, limit=15):
    """From a list of changed paths, the CAD file names (for the 'close and reopen' warning)."""
    names = [PurePosixPath(p).name for p in paths if p.startswith("cad/")]
    if len(names) > limit:
        names = names[:limit] + [f"... and {len(names) - limit} more"]
    return names


def shorten(text, limit=1200):
    """Keep very long error text from filling the screen."""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n... (the full text is in the log)"


# ---------------------------------------------------------------------------
# History window
# ---------------------------------------------------------------------------

EVENT_LABELS = {
    "created": "Created", "checked_out": "Checked out", "checked_in": "Checked in",
    "released": "Released", "reopened": "Reopened", "voided": "Voided", "made_cots": "Made COTS",
    "edited": "Edited details", "revised": "Revised", "revision_cancelled": "Revision cancelled",
    "references_updated": "Parts used updated",
    "release_requested": "Release requested", "release_signed": "Signed off", "release_rejected": "Release rejected",
    "release_withdrawn": "Request withdrawn",
}


def to_display_time(text, local=True):
    """'2026-10-05T14:02:41Z' -> '2026-10-05 14:02' (in your time zone if local=True)."""
    try:
        moment = datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return str(text)
    if local:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


def format_history(record, local=True):
    """Rows of (when, who, what, details) for a record, newest first."""
    rows = []
    for event in reversed(record.history):
        parts = []
        if event.get("reason"):
            parts.append(str(event["reason"]))
        if event.get("comment"):
            parts.append(str(event["comment"]))
        if event.get("event") == "revised" and event.get("from_revision"):
            parts.append(f"Rev {event['from_revision']} to Rev {event.get('revision', '')}")
        if event.get("event") == "revision_cancelled" and event.get("cancelled"):
            parts.append(f"Rev {event['cancelled']}")
        used = event.get("references")
        if used is not None and event.get("event") == "checked_in":
            parts.append("uses " + (", ".join(used) if used else "no parts"))
        elif isinstance(used, dict):
            parts.append("; ".join(f"Rev {rev} uses " + (", ".join(stems) if stems else "no parts")
                                   for rev, stems in used.items()))
        changes = event.get("changes") or []
        if changes:
            parts.append("; ".join(str(c) for c in changes))
        if event.get("event") == "release_signed" and event.get("roles"):
            parts.append("as " + ", ".join(event["roles"]))
        if event.get("event") == "release_requested" and event.get("waiting_on"):
            parts.append("needs " + ", ".join(event["waiting_on"]))
        if event.get("event") == "release_rejected" and event.get("signed"):
            parts.append("had been signed by " + ", ".join(event["signed"]))
        if event.get("event") == "released" and event.get("signoffs"):
            parts.append("signed off by " + ", ".join(event["signoffs"]))
        files = event.get("files") or []
        if files:
            parts.append(", ".join(PurePosixPath(f).name for f in files))
        name = event.get("event", "")
        label = EVENT_LABELS.get(name, str(name))
        if name == "released" and event.get("override"):
            label = "Released (Admin override)"
        rows.append((
            to_display_time(event.get("at", ""), local),
            str(event.get("by", "")),
            label,
            "  -  ".join(parts),
        ))
    return rows


# ---------------------------------------------------------------------------
# Orgs: each org is one vault folder. settings.yaml remembers them.
#
#   orgs:
#     HCR: C:\Litterbox\hcr-litterbox
#     SAE: C:\Litterbox\sae-litterbox
#   last_org: HCR
# ---------------------------------------------------------------------------

ADD_ORG = "Add org..."
CREATE_VAULT = "Create new vault..."
EDIT_ORG = "Org setup..."


def known_orgs(data):
    """{org code: vault folder} from the personal settings. Bad entries are ignored."""
    orgs = data.get("orgs")
    if not isinstance(orgs, dict):
        return {}
    return {str(code).upper(): str(path) for code, path in orgs.items() if code and path}


def migrate_settings(data, detect_org):
    """Older settings only had one 'repo'. Turn it into an org entry.

    detect_org(folder) returns the folder's org code, or None if it can't tell.
    Returns True if the settings changed.
    """
    if known_orgs(data) or not data.get("repo"):
        return False
    code = detect_org(data["repo"])
    if not code:
        return False
    data["orgs"] = {code: data["repo"]}
    data["last_org"] = code
    return True


def current_org(data):
    """The org to open: the last one worked on if it is still known, else the first known one."""
    orgs = known_orgs(data)
    last = str(data.get("last_org") or "").upper()
    if last in orgs:
        return last
    return next(iter(orgs), None)


def org_menu_values(data):
    """The dropdown entries: every known org, then the two setup actions."""
    return list(known_orgs(data)) + [ADD_ORG, CREATE_VAULT, EDIT_ORG]


CREATE_VAULT_INTRO = (
    "A new vault starts as an empty repository on your Git host (Azure DevOps, GitHub or GitLab).\n\n"
    "1. Create the empty repository on the host.\n"
    "2. Clone it to this computer (for example into C:\\Litterbox).\n"
    "3. Come back here and choose the cloned folder.\n\n"
    "Litterbox will then add its settings, upload them, and make you the team's Owner. "
    "Have you cloned the empty repository?")


def vault_created_text(result):
    """What to tell the user after init_vault.create() worked. `result` is an init_vault.InitResult."""
    lines = [f"The {result.org} vault is set up" + (" and uploaded." if result.pushed else " on this computer only.")]
    if result.owner is not None:
        lines.append(f"{result.owner.name} is the team's Owner.")
    elif result.team_error:
        lines.append("The team could not be set up just now, so everyone can still do everything. "
                     f"Use Team... to set it up later.\n\n{shorten(result.team_error)}")
    lines.extend(result.warnings)
    return "\n\n".join(lines)


def remember_org(data, org, folder):
    """Add or update an org and make it the last one worked on."""
    orgs = known_orgs(data)
    orgs[org.upper()] = str(folder)
    data["orgs"] = orgs
    data["last_org"] = org.upper()
    data["repo"] = str(folder)            # kept so older copies of the app still open something
    return data


# ---------------------------------------------------------------------------
# New Part / New Variant dialogs
# ---------------------------------------------------------------------------

def parse_number(text, label, minimum=1, maximum=None):
    """A whole number typed into a box. Raises ValueError with a message safe to show."""
    text = str(text or "").strip()
    if not text:
        raise ValueError(f"Enter the {label}.")
    if not (text.isascii() and text.isdigit()):
        raise ValueError(f"The {label} must be a whole number, like 42.")
    number = int(text)
    if number < minimum:
        raise ValueError(f"The {label} must be {minimum} or higher.")
    if maximum is not None and number > maximum:
        raise ValueError(f"The {label} can be at most {maximum}.")
    return number


def parse_typed_number(text, label, digits):
    """A number typed into the part number or variant box, which must be written exactly.

    An empty box gives None (use the suggested number). Otherwise the text must
    be exactly `digits` plain digits, so with 5 digits "00002" is accepted but
    "2" and "000002" are not. Raises ValueError with a message safe to show.
    """
    text = str(text or "").strip()
    if not text:
        return None
    example = f"{1:0{digits}d}"
    if not (text.isascii() and text.isdigit()) or len(text) != digits:
        raise ValueError(f"The {label} must be exactly {digits} digits, like {example}.")
    number = int(text)
    if number < 1:
        raise ValueError(f"The {label} can't be {text}. The lowest is {example}.")
    return number


def parse_digit_count(text, label, low, high):
    """The number of digits typed in the org setup. Raises ValueError with a message safe to show."""
    text = str(text or "").strip()
    if not (text.isascii() and text.isdigit()) or not (low <= int(text) <= high):
        raise ValueError(f"The {label} must be a whole number from {low} to {high}.")
    return int(text)


def in_use_text(check):
    """The line shown under "PN in use:": the name of the part that has the number."""
    text = check.name or "(no name)"
    return text + (" (void)" if check.status == "void" else "")


def parse_optional_number(text, label, minimum=1, maximum=None):
    """Like parse_number, but an empty box gives None (meaning: use the suggested number)."""
    if not str(text or "").strip():
        return None
    return parse_number(text, label, minimum, maximum)


def variant_lines(records):
    """One line per existing variant, for the New Variant list."""
    lines = []
    for record in records:
        status = "" if record.status == "in_work" else f"  [{record.status}]"
        lines.append(f"{record.pn}{status}   {record.name}")
    return lines


# ---------------------------------------------------------------------------
# The Import window: what the table shows and what editing a cell does
# ---------------------------------------------------------------------------

IMPORT_KIND_LABELS = {"part": "Part", "assembly": "Assembly", "drawing": "Drawing only"}
IMPORT_TAGS = ("conflict", "off", "typed", "warn", "ok")      # strongest first
EDITABLE_COLUMNS = ("pn", "name", "description")


@dataclass
class ImportRow:
    item_id: int
    ticked: bool
    pn: str
    name: str
    description: str
    kind: str
    files: str
    notes: str
    tag: str            # how the row is coloured: see IMPORT_TAGS
    detail: str         # everything worth saying about the row, shown under the table when it is selected


def import_rows(candidates, proposal, conflicts=(), duplicates=None):
    """One ImportRow per item that could be imported, in order. `conflicts` come from importer.Refresh/PNConflict.

    Rows that are ticked show their new part number; unticked rows show none and are greyed.
    """
    placed = {id(entry.item): (index, entry) for index, entry in enumerate(proposal.entries)}
    problems = {c.index: c for c in conflicts}
    duplicates = duplicates or {}
    rows = []
    for item in candidates:
        files = ", ".join(sorted({f.type for f in item.files if f.type}))
        kind = IMPORT_KIND_LABELS.get(item.kind, item.kind)
        details = []
        if id(item) in placed:
            index, entry = placed[id(item)]
            conflict = problems.get(index)
            if conflict:
                tag, notes = "conflict", "Number taken: change it"
                details.append(conflict.reason)
            elif entry.manual:
                tag, notes = "typed", ""
            else:
                tag, notes = "ok", ""
            if duplicates.get(index):
                details = duplicates[index] + details
                if not conflict:
                    notes = "Possible duplicate"
                    tag = "warn"
            pn, name, description, ticked = str(entry.pn), entry.name, entry.description, True
        else:
            pn, name, description, ticked, tag, notes = "", item.name, item.description, False, "off", ""
        details += item.warnings
        if item.already_imported_as:
            details.append(f"Already imported as {item.already_imported_as}.")
        if item.identical_to:
            details.append("Identical file in item(s): " + ", ".join(str(i) for i in item.identical_to) + ".")
        details.append("Files: " + "; ".join(f.path for f in item.files))
        if not notes and (item.warnings or item.already_imported_as):
            first = item.warnings[0] if item.warnings else f"Already imported as {item.already_imported_as}"
            extra = len(item.warnings) - 1
            notes = first if len(first) <= 60 else first[:57] + "..."
            notes += f" (+{extra} more)" if extra > 0 else ""
            if tag in ("ok",):
                tag = "warn"
        rows.append(ImportRow(item.id, ticked, pn, name, description, kind, files, notes, tag, "\n".join(details)))
    return rows


def edit_import_cell(prepared, item_id, column, text):
    """Apply an edit made in the table. Returns '' if it worked, else a message to show the user."""
    import create
    import importer
    item = next((i for i in prepared.candidates if i.id == item_id), None)
    if item is None or column not in EDITABLE_COLUMNS:
        return "That cell can't be edited."
    entries = prepared.proposal.entries
    index = next((n for n, e in enumerate(entries) if e.item is item), None)
    text = " ".join(str(text).split()) if column != "pn" else str(text).strip()
    if column == "pn":
        if index is None:
            return "Tick the row first: unticked rows are not given a part number."
        if not text:
            prepared.proposal.reset_pn(index)
            return ""
        try:
            prepared.proposal.set_pn(index, text)
        except importer.ImportFailed as e:
            return str(e)
        return ""
    if column == "name":
        if not text:
            return "A name is required."
        if len(text) > create.MAX_NAME:
            return f"Keep the name under {create.MAX_NAME} characters."
    elif len(text) > create.MAX_DESCRIPTION:
        return f"Keep the description under {create.MAX_DESCRIPTION} characters."
    if index is None:
        item.name, item.description = (text, item.description) if column == "name" else (item.name, text)
    elif column == "name":
        entries[index].name = text
    else:
        entries[index].description = text
    return ""


def import_summary_line(candidates, proposal, conflicts=()):
    """The line above the table."""
    ticked, total = len(proposal.entries), len(candidates)
    text = f"{ticked} of {total} items will be imported"
    if conflicts:
        text += f"   |   {len(conflicts)} part number(s) can't be used (shown in red)"
    return text


def import_conflict_text(conflicts, renumbered=()):
    """The message shown when Finish & Import is refused because typed part numbers are taken."""
    lines = ["These part numbers can't be used:", ""]
    lines += [f"  Row {c.index + 1}: {c.reason}" for c in conflicts]
    lines += ["", "Change the part number in the highlighted rows (or clear it to let Litterbox choose), "
              "then press Finish & Import again. Nothing was imported."]
    if renumbered:
        lines += ["", f"{len(renumbered)} automatic number(s) were also replaced because they had been taken."]
    return "\n".join(lines)


def import_result_text(result):
    count = len(result.pns)
    text = f"Imported {_parts(count)}: {min(result.pns)}" + (f" to {max(result.pns)}" if count > 1 else "") + "."
    text += f"\n{len(result.files)} CAD file(s) were copied into the vault. Your original files were not changed."
    if result.renumbered:
        text += f"\n{len(result.renumbered)} automatic part number(s) had been taken meanwhile and were replaced."
    if result.warnings:
        text += "\n\nNotes:\n" + "\n".join("  " + w for w in result.warnings[:8])
    return text


def edit_import_pn(prepared, item_id, base_text, variant_text, repo=None):
    """Apply a part number typed into the two boxes [base]-[variant]. Returns '' if it worked, else a message.

    Both boxes empty gives the row back to Litterbox. Only one box filled in: an empty variant means the
    lowest free variant of that part number (as in New Part), an empty base keeps the row's current base.
    Typing the numbers the row already has changes nothing (the row stays automatic).
    """
    import registry
    item = next((i for i in prepared.candidates if i.id == item_id), None)
    entries = prepared.proposal.entries
    index = next((n for n, e in enumerate(entries) if item is not None and e.item is item), None)
    if item is None:
        return "That cell can't be edited."
    if index is None:
        return "Tick the row first: unticked rows are not given a part number."
    try:
        base = parse_typed_number(base_text, "part number", pn_module.BASE_DIGITS)
        variant = parse_typed_number(variant_text, "variant number", pn_module.VARIANT_DIGITS)
    except ValueError as e:
        return str(e)
    if base is None and variant is None:
        prepared.proposal.reset_pn(index)
        return ""
    entry, org = entries[index], prepared.proposal.org
    if base is None:
        base = entry.pn.base
    if variant is None:
        try:
            variant = registry.next_free_variant(repo, base, org) if repo else 1
        except Exception:
            variant = 1
    chosen = pn_module.PN(org, base, variant)
    if chosen == entry.pn:
        return ""
    try:
        prepared.proposal.set_pn(index, str(chosen))
    except LitterboxError as e:
        return str(e)
    return ""


def import_external_text(error):
    """The question asked when some files use files that are not part of the import."""
    shown = [f"  {Path(file).name}  uses  {ref}" for file, ref in error.references[:10]]
    more = len(error.references) - len(shown)
    lines = [f"{len(error.references)} file reference(s) point at files that are not being imported:", ""] + shown
    if more > 0:
        lines.append(f"  ...and {more} more")
    lines += ["", "If you continue, the imported copies will still depend on those original files. They will only "
              "open completely on computers that have them at those paths, and the vault will not be "
              "self-contained.", "",
              "Usually it is better to say No, tick the missing items (or scan their folder as well) and import again.",
              "", "Import anyway?"]
    return "\n".join(lines)


def import_cots_confirm_text(count, duplicates, names):
    """The question asked before an Import COTS goes ahead. `duplicates` is {row: [warnings]}; names[row] is the row's name."""
    lines = [f"You are about to import {_parts(count)} and record every one as COTS (a purchased part).",
             "", "Only choose this for parts you bought and have NOT modified. Anything you changed or "
             "designed yourself should be imported with the normal Import."]
    if duplicates:
        lines += ["", "These look like parts the vault already has (this is only a warning):"]
        for row in sorted(duplicates)[:8]:
            lines.append(f"  Row {row + 1}, {names[row]}:")
            lines += [f"      {text}" for text in duplicates[row][:3]]
        if len(duplicates) > 8:
            lines.append(f"  ...and {len(duplicates) - 8} more")
    lines += ["", "Import them as COTS?"]
    return "\n".join(lines)


def make_cots_problem_text(pn, problems):
    return f"{pn} can't be made COTS yet:\n\n" + "\n".join("- " + p for p in problems)


def make_cots_confirm_text(pn, name, files):
    listing = "\n".join("  " + f for f in files)
    return (f"Record {pn} ({name}) as COTS, a purchased part?\n\nThese files are covered:\n{listing}\n\n"
            "Only do this for a part you bought and have NOT modified. Nobody will be able to check it out "
            "afterwards, so its files can't be changed.")


def reopen_cots_warning(pn):
    return (f"{pn} is a COTS part.\n\nReopening it makes it a normal part again: it can be checked out and "
            "changed until it is released or made COTS again.\n\nContinue?")


def edit_details_result(old_name, old_description, name, description):
    """What the Edit Details window should do with what was typed.

    Returns (problem, changed): `problem` is text to show if the name is blank, else "";
    `changed` is whether anything differs from the old values (extra spaces don't count).
    """
    clean = lambda text: " ".join((text or "").split())
    if not clean(name):
        return "A name is required.", False
    return "", (clean(name), clean(description)) != (clean(old_name), clean(old_description))


def row_revisions(row):
    """{revision: [files]} for a part row (older test rows only have .files for the working revision)."""
    revisions = getattr(row, "revisions", None)
    if revisions:
        return revisions
    return {getattr(row, "revision", "A"): list(row.files)} if row.files else {}


def open_choices(row, drawing=False):
    """[(revision, files)] that Open (or Open Drawing) can open for this part.

    Normally one. When the part has both a released revision and a different working revision
    with files, both are offered, working first, and the user is asked which to open.
    With drawing=True only revisions that have a drawing are offered.
    """
    revisions = row_revisions(row)
    working = getattr(row, "revision", "A")
    released = getattr(row, "released_revision", "")
    wanted = []
    if revisions.get(working):
        wanted.append(working)
    if released and released != working and revisions.get(released):
        wanted.append(released)
    if not wanted and revisions:                       # fall back to the newest revision that has files
        wanted.append(max(revisions, key=pn_module.revision_number))
    choices = [(rev, revisions[rev]) for rev in wanted]
    if drawing:
        choices = [(rev, files) for rev, files in choices if _has_drawing(files)]
    return choices


def _has_drawing(files):
    return any(PurePosixPath(f).suffix.lower() == ".slddrw" for f in files)


def revision_label(row, rev):
    """'Rev B (working)' / 'Rev A (released)' for the question asked before opening."""
    released = getattr(row, "released_revision", "")
    if rev == released and not (rev == getattr(row, "revision", "") and row.record_status != "released"):
        return f"Rev {rev} (released)"
    return f"Rev {rev} (working)"


def open_message(row, drawing=False):
    """Why a part's model (or drawing) can't be opened right now, or '' if it can."""
    if not any(row_revisions(row).values()):
        return f"{row.pn} has no CAD files yet."
    if drawing and not open_choices(row, drawing=True):
        return f"{row.pn} has no drawing."
    return ""


def revision_rows(record, revisions):
    """Rows of (revision, state, details) for the History window's revision list, newest first.

    `revisions` is {revision: [files]}. A revision appears if it has files, is the working
    revision, or was released at some point.
    """
    released = {}
    for event in record.history:
        if event.get("event") == "released" and event.get("revision"):
            released[event["revision"]] = event
    cancelled = set(registry.cancelled_revisions(record))
    letters = set(revisions) | set(released) | {record.revision} | cancelled
    rows = []
    for rev in sorted(letters, key=pn_module.revision_number, reverse=True):
        event = released.get(rev)
        if rev in cancelled:
            rows.append((rev, "Cancelled", "kept in the cancelled-revs folder"))
            continue
        if rev == record.revision and record.status != "released":
            state = "In work" if record.status == "in_work" else record.status.replace("_", " ").title()
        elif event:
            state = "Released" if rev == record.released_revision else "Released (superseded)"
        else:
            state = "No release"
        details = []
        if event:
            details.append(f"by {event.get('by', '')} on {to_display_time(event.get('at', ''))}")
        types = file_types(revisions.get(rev, []))
        details.append(types if types else "no files")
        rows.append((rev, state, "   ".join(details)))
    return rows


def void_problem(row):
    """Why a part can't be voided (empty if it can). Once a revision is released a part can't disappear."""
    released = getattr(row, "released_revision", "")
    if released:
        return (f"{row.pn} has a released revision (Rev {released}), so it can't be voided. "
                "To throw away the revision that is in work, use Cancel Revision.")
    return ""


def revise_problem_text(pn, problems):
    return f"{pn} can't be revised yet:\n\n" + "\n".join("- " + p for p in problems)


def revise_confirm_text(plan):
    new_files = "\n".join("  " + PurePosixPath(new).name for _old, new in plan.copies)
    text = (f"Make Rev {plan.new_revision} of {plan.pn} ({plan.name})?\n\n"
            f"These files will be created from Rev {plan.revision}:\n{new_files}\n\n"
            f"Rev {plan.revision} stays released and unchanged, and anything that uses it keeps working. "
            f"Rev {plan.new_revision} will be checked out to you.")
    if plan.kept:
        text += "\n\nThese files stay with Rev %s: %s." % (
            plan.revision, ", ".join(PurePosixPath(f).name for f in plan.kept))
    return text


def cancel_problem_text(pn, problems):
    return f"The revision of {pn} can't be cancelled yet:\n\n" + "\n".join("- " + p for p in problems)


def cancel_confirm_text(plan):
    kept = "\n".join("  " + PurePosixPath(new).name for _old, new in plan.moves) or "  (no files)"
    return (f"Cancel Rev {plan.revision} of {plan.pn} ({plan.name})?\n\n"
            f"Its files are not deleted. They are kept in the cancelled-revs folder as:\n{kept}\n\n"
            f"The part goes back to Rev {plan.back_to}, and the letter {plan.revision} will not be used again. "
            f"Any assembly that already uses Rev {plan.revision} will lose it.")


# ---------------------------------------------------------------------------
# References: what an assembly uses, where a part is used, and replacing with the latest release
# ---------------------------------------------------------------------------

CHECKED, UNCHECKED = "\u2611", "\u2610"


def uses_table(uses_list):
    """Rows for the 'Uses' table: (id, (tick, part, name, rev used, latest released, state), replaceable)."""
    rows = []
    for number, u in enumerate(uses_list):
        rows.append((str(number),
                     (CHECKED if u.replaceable else "", u.child.short, u.child_name, u.child_revision,
                      u.latest_released, u.state_text),
                     u.replaceable))
    return rows


def used_in_table(uses_list):
    """Rows for the 'Used in' table: (id, (tick, assembly, name, its rev, its status, rev of this part used, state), replaceable)."""
    rows = []
    for number, u in enumerate(uses_list):
        status = "Released" if u.parent_status == "released" else "In work"
        rows.append((str(number),
                     (CHECKED if u.replaceable else "", u.parent.short, u.parent_name, u.parent_revision,
                      status, u.child_revision, u.state_text),
                     u.replaceable))
    return rows


def toggled(mark):
    """The tick box after a click ('' means there is no box)."""
    return {CHECKED: UNCHECKED, UNCHECKED: CHECKED}.get(mark, mark)


def release_confirm_text(plan):
    listing = "\n".join("  " + f for f in plan.files)
    text = (f"Release {plan.pn} ({plan.name})?\n\nThese files will be frozen:\n{listing}\n\n"
            "Nobody will be able to check it out unless it is reopened.")
    if plan.warnings:
        text += ("\n\nWARNING - the parts it uses are not all final:\n"
                 + "\n".join("- " + w for w in plan.warnings)
                 + "\n\nReleasing now freezes the assembly with those parts.")
    return text


def request_release_text(plan, template, warnings=()):
    """The question asked before a release request is made (a vault with a release workflow)."""
    listing = "\n".join("  " + f for f in plan.files)
    needs = "\n".join(f"  {step.role}" + (f" ({step.count} people)" if step.count != 1 else "") for step in template.steps)
    text = (f"Ask for sign-offs to release {plan.pn} ({plan.name})?\n\nIt will be released when these have signed:\n"
            f"{needs}\n\nThey are shown these files:\n{listing}\n\nWhile it waits, nobody can check the part out. "
            "You can withdraw the request until it is released.")
    if not template.allow_self_signoff:
        text += "\n\nYou can't sign off your own request."
    if plan.warnings:
        text += ("\n\nWARNING - the parts it uses are not all final:\n" + "\n".join("- " + w for w in plan.warnings))
    if warnings:
        text += "\n\nNOTE:\n" + "\n".join("- " + w for w in warnings)
    return text


TASK_COLUMNS = (("part", "Part", 130), ("name", "Name", 220), ("rev", "Rev", 40), ("by", "Asked by", 130),
                ("when", "Asked", 120), ("status", "Status", 330))


def tasks_table(tasks, local=True):
    """Rows of (iid, values) for the My Tasks window."""
    return [(str(t.pn), (str(t.pn), t.name, t.revision, t.requested_by, to_display_time(t.requested_at, local),
                         t.summary)) for t in tasks]


def tasks_button_text(count):
    return f"My Tasks ({count})" if count else "My Tasks"


def signoff_failure_text(pn, error):
    return (f"Your sign-off on {pn} is saved, and everyone needed has now signed, but the release itself did not "
            f"go through:\n\n{error}\n\nWhoever asked for the release (or anyone) can finish it from My Tasks "
            "or with the Release button.")


def workflow_rows(template):
    """[(role, count)] for the Workflows dialog from a workflow.Template (or None)."""
    return [(s.role, s.count) for s in template.steps] if template else []


def parse_signoff_count(text):
    """Whole number 1 to 20 from the box, or None."""
    text = str(text).strip()
    if text.isdigit() and 1 <= int(text) <= 20:
        return int(text)
    return None


def stale_open_text(pn, uses_list):
    lines = "\n".join(f"  {u.child.short} Rev {u.child_revision} (Rev {u.latest_released} is released)"
                      for u in uses_list)
    return (f"{pn.short} uses parts that have a newer released revision:\n\n{lines}\n\n"
            "Review them before opening?")


def replace_summary(results):
    """(text, had_problems) for a list of ReplaceResult."""
    names = {"done": "updated and checked in", "left_checked_out": "changed, still checked out to you",
             "skipped": "skipped", "failed": "FAILED"}
    lines = []
    for r in results:
        lines.append(f"{r.parent.short}: {names.get(r.status, r.status)}" + (f" - {r.message}" if r.status != "done" and r.message else ""))
    problems = any(r.status in ("skipped", "failed") for r in results)
    done = sum(r.status in ("done", "left_checked_out") for r in results)
    head = f"{done} of {len(results)} assemblies updated."
    return head + "\n\n" + "\n".join(lines), problems


def outdated_note(pn, this_outdated, others):
    """The yellow banner in the References window ('' if every list of parts is up to date)."""
    lines = []
    if this_outdated:
        lines.append(f"The list of parts {pn.short} uses is out of date (SolidWorks was not open at its last check-in, "
                     "or it was never read).")
    if others:
        lines.append(f"{len(others)} other assembl{'y has' if len(others) == 1 else 'ies have'} an out-of-date list, "
                     "so 'This part is used in' may be incomplete.")
    return "\n".join(lines)


def update_summary(results):
    """(text, had_problems) for rescan's {PN: result}."""
    updated = sum(1 for r in results.values() if r == "updated")
    skipped = {pn: r for pn, r in results.items() if r.startswith("skipped")}
    text = f"{updated} of {len(results)} assemblies updated."
    if skipped:
        text += "\n\n" + "\n".join(f"{pn.short}: {r}" for pn, r in skipped.items())
    return text, bool(skipped)


# ---------------------------------------------------------------------------
# The team: who you are, the people table, and the Add/Edit Person form
# ---------------------------------------------------------------------------

def identity_banner(identity):
    """(text, tone) for the line under the title. tone is 'normal' or 'warn'."""
    text = identity.describe()
    return text, ("normal" if identity.state in ("ok", "legacy") else "warn")


def people_table(directory):
    """Rows for the Team window: (id, (name, email, access, roles, active, host names, keys))."""
    rows = []
    for p in directory.people:
        rows.append((p.id, (p.name, p.email, p.label, ", ".join(p.roles), "Yes" if p.active else "No",
                            ", ".join(p.host_names), len(p.signing_keys) or "")))
    return rows


def split_list(text):
    """'a, b\nc' -> ['a', 'b', 'c'] (commas or new lines)."""
    return [part.strip() for part in str(text or "").replace("\n", ",").split(",") if part.strip()]


def suggest_person_id(name, existing):
    """A short lowercase id from a name ('Alex Smith' -> 'alex-smith'), made unique among `existing`."""
    import re
    base = re.sub(r"[^a-z0-9._-]+", "-", str(name).lower()).strip("-.")[:36] or "person"
    taken = {str(e).lower() for e in existing}
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    return candidate


def who_am_i_text(identity):
    lines = [f"The host says you are signed in as: {identity.host_name or '(unknown)'}"]
    if identity.state == "legacy":
        lines.append("This vault has no team list yet, so everyone can do everything.")
    elif identity.state == "ok":
        p = identity.person
        lines.append(f"That matches {p.name} on the team list: {p.label}"
                     + (f", {', '.join(p.roles)}" if p.roles else "") + ".")
    else:
        lines.append(identity.message())
    return "\n\n".join(lines)


def person_form_result(old_id, form, existing_ids):
    """Check the Add/Edit Person form. Returns (problem text, fields dict). `form` has name, email,
    host_names, roles, keys, id and access (all text)."""
    name = " ".join(str(form.get("name", "")).split())
    if not name:
        return "Enter a name.", {}
    email = str(form.get("email", "")).strip()
    if email and "@" not in email:
        return "That doesn't look like an email address.", {}
    fields = {"name": name, "email": email, "host_names": split_list(form.get("host_names")),
              "roles": split_list(form.get("roles")), "signing_keys": [line.strip() for line in str(form.get("keys", "")).splitlines() if line.strip()],
              "access": str(form.get("access", "member")).strip().lower()}
    if old_id is None:
        fields["id"] = str(form.get("id", "")).strip().lower() or suggest_person_id(name, existing_ids)
    return "", fields


def add_role_result(text, roles):
    """Check a role typed into the Roles window. Returns (problem, tidy role name)."""
    role = " ".join(str(text or "").split())
    if not role:
        return "Type a role first.", ""
    if "," in role:
        return "A role can't contain a comma.", ""
    if role.lower() in (r.lower() for r in roles):
        return f"'{role}' is already on the list.", ""
    return "", role


def role_removal_text(role, holders):
    if not holders:
        return f"Remove the role '{role}' from the list?"
    names = ", ".join(holders[:8]) + (f" and {len(holders) - 8} more" if len(holders) > 8 else "")
    return (f"Remove the role '{role}'?\n\nIt will also be taken off everyone who has it ({names}). "
            "This happens when you press Save.")


def roles_to_choose(all_roles, chosen):
    """The roles a person doesn't have yet, for the drop-down."""
    have = {r.lower() for r in chosen}
    return [r for r in all_roles if r.lower() not in have]
