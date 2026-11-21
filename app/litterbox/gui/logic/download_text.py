"""
download_text.py - what the window says about downloading CAD files on demand (see parts/downloads.py).
"""

DOWNLOAD_ALL_QUESTION = ("Download every CAD file in this vault?\n\n"
                         "Litterbox normally downloads a part's files only when you check it out or open it. Download "
                         "All gets everything now, which can be a lot of data, and Get Latest then keeps it all up to "
                         "date.\n\nTo make this the default, add  download: all  to C:\\Litterbox\\settings.yaml.")


def _files(count):
    return "1 file" if count == 1 else f"{count} files"


def downloading_label(pn, count):
    """What the banner says while a part's files are downloaded before opening it."""
    return f"Downloading {_files(count)} for {pn.short}"


def downloaded_for_open(pn, revision, count):
    return f"Downloaded {_files(count)} for {pn.short} Rev {revision}"


# -- Repair Files (Vault menu, parts/file_repair.py) ------------------------------------------------------------------
REPAIR_NOTHING = ("Every CAD file and document on this computer that you don't have checked out matches the vault's "
                  "copy. Nothing needs repairing.\n\nIf SolidWorks still says a file is damaged, it may not be "
                  "downloaded yet: open it from Litterbox, or use Download All.")

_SHOWN = 12


def _list(files):
    shown = "\n".join(f"  {rel}" for rel in files[:_SHOWN])
    return shown + (f"\n  ...and {len(files) - _SHOWN} more" if len(files) > _SHOWN else "")


def repair_question(files):
    """Ask before putting back the vault's copy of these files (file_repair.find)."""
    return (f"{_files(len(files))} on this computer {'doesn' if len(files) == 1 else 'don'}'t match the vault's copy, "
            f"and you don't have {'it' if len(files) == 1 else 'them'} checked out:\n\n{_list(files)}\n\n"
            "This usually means a download or a sync was cut off part-way. Repair puts back the vault's copy and "
            "downloads it again. Any changes in these files are lost. Files you have checked out are left alone.\n\n"
            "Close them in SolidWorks first. Repair them now?")


def repair_summary(result):
    """(title, text, problem?) after Repair Files (a file_repair.RepairResult)."""
    lines = []
    if result.repaired:
        lines.append(f"Repaired {_files(len(result.repaired))}: each is the vault's copy again.")
    if result.not_downloaded:
        lines.append(f"{_files(len(result.not_downloaded))} put back but not downloaded (are you online?). Open "
                     f"them from Litterbox, or use Download All, to download them:\n{_list(result.not_downloaded)}")
    if result.failed:
        detail = "\n".join(f"  {rel}: {why}" for rel, why in list(result.failed.items())[:_SHOWN])
        lines.append(f"{_files(len(result.failed))} couldn't be put back. If SolidWorks or another program has "
                     f"{'it' if len(result.failed) == 1 else 'them'} open, close it and repair again:\n{detail}")
    if not lines:
        lines.append("Nothing needed repairing: you have those files checked out now.")
    problem = bool(result.failed or result.not_downloaded)
    return ("Repair Files", "\n\n".join(lines), problem)
