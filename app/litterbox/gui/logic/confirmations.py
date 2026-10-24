"""
confirmations.py - the "Are you sure?" and "can't do that" texts for Release, Make COTS, Unrelease, Void,
Revise, Cancel Revision and Edit Details.
"""

from pathlib import PurePosixPath

from litterbox.core import file_types
from litterbox.gui.logic import action_rules


def make_cots_confirm_text(pn, name, files):
    listing = "\n".join("  " + f for f in files)
    return (f"Record {pn} ({name}) as COTS, a purchased part?\n\nThese files are covered:\n{listing}\n\n"
            "Only do this for a part you bought and have NOT modified. Nobody will be able to check it out "
            "afterwards, so its files can't be changed.")


def reopen_cots_warning(pns):
    """The question asked before unreleasing COTS parts: one part number, or a list of them."""
    if isinstance(pns, (list, tuple)) and len(pns) != 1:
        listing = "\n".join("  " + str(pn) for pn in pns)
        return (f"These are COTS parts:\n{listing}\n\nUnreleasing them makes them normal parts again: they can be "
                "checked out and changed until they are released or made COTS again.\n\nContinue?")
    pn = pns[0] if isinstance(pns, (list, tuple)) else pns
    return (f"{pn} is a COTS part.\n\nUnreleasing it makes it a normal part again: it can be checked out and "
            "changed until it is released or made COTS again.\n\nContinue?")


def plans_problem_text(plans, verb):
    """Why parts can't be released (or made COTS) yet: `verb` is 'released' or 'made COTS'. `plans` are the ones
    that have problems."""
    if len(plans) == 1:
        return f"{plans[0].pn} can't be {verb} yet:\n\n" + "\n".join("- " + p for p in plans[0].problems)
    return (f"These can't be {verb} yet:\n\n" + "\n\n".join(
        f"{plan.pn}:\n" + "\n".join("- " + p for p in plan.problems) for plan in plans))


def _skipped_text(bad, verb):
    if not bad:
        return ""
    return (f"\n\nThese can't be {verb} yet, so they will be skipped:\n"
            + "\n".join(f"  {plan.pn}: {plan.problems[0]}" for plan in bad))


def release_many_confirm_text(good, bad=()):
    """The question asked before releasing several parts (or documents) at once. `good` are the plans that can go
    ahead."""
    listing = "\n".join(f"  {plan.pn}  {plan.name}  ({len(plan.files)} file{'s' if len(plan.files) != 1 else ''})"
                        for plan in good)
    documents = action_rules.are_documents(plan.pn for plan in good)
    text = (f"Release these {action_rules.parts_text(len(good), documents)}?\n\n{listing}\n\n"
            f"Their {'' if documents else 'CAD '}files will be frozen. Nobody will be able to check them out unless "
            "they are unreleased.")
    warned = [plan for plan in good if plan.warnings]
    if warned:
        text += ("\n\nWARNING - the parts these use are not all final:\n" + "\n".join(
            f"- {plan.pn}: {w}" for plan in warned for w in plan.warnings)
            + "\n\nReleasing now freezes the assemblies with those parts.")
    return text + _skipped_text(bad, "released")


def make_cots_many_confirm_text(good, bad=()):
    """The question asked before making several parts COTS at once."""
    listing = "\n".join(f"  {plan.pn}  {plan.name}" for plan in good)
    return (f"Record these {len(good)} parts as COTS, purchased parts?\n\n{listing}\n\nOnly do this for parts you "
            "bought and have NOT modified. Nobody will be able to check them out afterwards, so their files can't "
            "be changed." + _skipped_text(bad, "made COTS"))


def void_many_confirm_text(pns):
    listing = "\n".join("  " + str(pn) for pn in pns)
    return (f"Void these {action_rules.parts_text(len(pns), action_rules.are_documents(pns))}?\n\n{listing}\n\nTheir numbers will never be used again, and they can't be "
            "checked out.")


def edit_details_result(old_name, old_description, name, description):
    """What the Edit Details window should do with what was typed.

    Returns (problem, changed): `problem` is text to show if the name is blank, else "";
    `changed` is whether anything differs from the old values (extra spaces don't count).
    """
    clean = lambda text: " ".join((text or "").split())
    if not clean(name):
        return "A name is required.", False
    return "", (clean(name), clean(description)) != (clean(old_name), clean(old_description))


def kind_note(row):
    """Why Edit Details can't switch a part between CAD and non-CAD ("" if it can): once released, a COTS part, or
    one with SolidWorks files."""
    if getattr(row, "released_revision", "") or getattr(row, "record_status", "in_work") != "in_work":
        return "It has been released, so its kind can't change."
    if getattr(row, "cots", False):
        return "A COTS part has a CAD model, so it stays CAD."
    if any(file_types.is_cad(f) for files in (getattr(row, "revisions", None) or {}).values() for f in files):
        return "It has SolidWorks files, so it stays CAD."
    return ""


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
    documents = action_rules.are_documents([plan.pn])
    return (f"Cancel Rev {plan.revision} of {plan.pn} ({plan.name})?\n\n"
            f"Its files are not deleted. They are kept in the cad\\cancelled-revs folder as:\n{kept}\n\n"
            f"The {'document' if documents else 'part'} goes back to Rev {plan.back_to}, and the letter "
            f"{plan.revision} will not be used again."
            + ("" if documents else f" Any assembly that already uses Rev {plan.revision} will lose it."))


def release_confirm_text(plan):
    listing = "\n".join("  " + f for f in plan.files)
    text = (f"Release {plan.pn} ({plan.name})?\n\nThese files will be frozen:\n{listing}\n\n"
            "Nobody will be able to check it out unless it is unreleased.")
    if plan.warnings:
        text += ("\n\nWARNING - the parts it uses are not all final:\n"
                 + "\n".join("- " + w for w in plan.warnings)
                 + "\n\nReleasing now freezes the assembly with those parts.")
    return text
