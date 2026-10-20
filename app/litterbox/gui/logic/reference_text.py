"""
reference_text.py - the References window's tables (uses, used in) and the summaries after Update
references.
"""



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
    updated = sum(1 for r in results.values() if r.startswith("updated"))
    skipped = {pn: r for pn, r in results.items() if r.startswith("skipped") or r.startswith("updated, but")}
    text = f"{updated} of {len(results)} assembl{'y' if len(results) == 1 else 'ies'} updated."
    if skipped:
        text += "\n\n" + "\n".join(f"{pn.short}: {r}" for pn, r in skipped.items())
    return text, bool(skipped)
