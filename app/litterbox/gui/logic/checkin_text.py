"""
checkin_text.py - texts around Check In, Save Progress and Undo: parts with no changes, the CAD files that
changed, and the caution while an upload is still running.
"""

from pathlib import PurePosixPath

from litterbox.gui.logic import action_rules


def recovered_text(folder, files):
    """What to say when a sync saved your copies of files whose checkout was broken (git/remote.py)."""
    names = "\n".join("  " + str(f).rsplit("/", 1)[-1] for f in files[:10]) + ("\n  ..." if len(files) > 10 else "")
    return (f"An Admin broke your checkout, and the vault has newer versions of these files:\n{names}\n\n"
            f"Your versions are saved in:\n  {folder}\n\nYour copy of the vault now has the newer ones. To carry on "
            "with yours, check the part out again and copy them back into the cad folder.")


def break_checkout_prompt(pn, who):
    """The question before Break Checkout."""
    return (f"Break {who}'s checkout of {pn}?\n\n"
            f"Their locks are released and anyone can check {pn} out. Changes {who} hasn't checked in are not "
            "uploaded; they stay on their computer. When they next sync, Litterbox puts the part back as it is in "
            "the vault and saves their versions of its CAD files beside the vault, so nothing is lost.\n\n"
            "The part's history will say you did this, and why.")


def undo_prompt(targets):
    """The question asked before Undo Checkout."""
    noun = "documents" if action_rules.are_documents(targets) else "parts"
    return (f"This will discard changes and release the lock on these {noun}:\n\n"
            + "\n".join(str(pn) for pn in targets) + "\n\nContinue?")


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
            lines.append("    (no files yet)" if action_rules.are_documents([pn]) else "    (no CAD files yet)")
    return lines


def cad_changes(paths, limit=15):
    """From a list of changed paths, the CAD file names (for the 'close and reopen' warning)."""
    names = [PurePosixPath(p).name for p in paths if p.startswith("cad/")]
    if len(names) > limit:
        names = names[:limit] + [f"... and {len(names) - limit} more"]
    return names


def comment_heading(count, keep_lock):
    """The line above the list in the check-in comment window."""
    what = "Save progress on" if keep_lock else "Check in"
    return f"{what} these {count}:" if count != 1 else f"{what} this one:"


def comment_lines(targets, rows_by_pn):
    """One line per part (or document) being checked in: its number, revision and name."""
    lines = []
    for pn in targets:
        row = rows_by_pn.get(pn)
        name = getattr(row, "name", "") if row is not None else ""
        revision = getattr(row, "revision", "") if row is not None else ""
        lines.append("   ".join(text for text in (str(pn), f"Rev {revision}" if revision else "", name) if text))
    return lines


CHECKIN_CAUTION = ("Litterbox uploads in the background. Until the banner says Ready, don't open these files and "
                   "don't save them: a save in the middle of an upload can end up half in the vault.")


def open_while_busy_text(pn, label):
    """The question asked before opening a part that has a job queued or running."""
    return (f"{pn} is busy: {label.lower()}.\n\nOpening it now is safe, but don't save it in SolidWorks until the "
            "banner says Ready, or the upload can end up half in the vault.\n\nOpen it anyway?")


def warnings_text(warnings, limit=8):
    """What the window says after a check-in that read something worth a look (parts/configuration_check.py)."""
    shown = list(warnings[:limit])
    if len(warnings) > limit:
        shown.append(f"... and {len(warnings) - limit} more (the log has them all).")
    return "The check-in went ahead. Worth a look:\n\n" + "\n\n".join(shown)
