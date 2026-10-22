"""
vault_size_text.py - Vault > Vault Size... in words (git/vault_size.py measures it): sizes people read at a glance,
and what each number means.
"""

UNITS = ("bytes", "KB", "MB", "GB", "TB")


def readable(count):
    """1536 -> '1.5 KB', 32_296_141 -> '30.8 MB' (1 KB = 1024 bytes, as Windows Explorer counts)."""
    value, unit = float(count), 0
    while value >= 1024 and unit < len(UNITS) - 1:
        value, unit = value / 1024, unit + 1
    return f"{int(value)} bytes" if unit == 0 else f"{value:.1f} {UNITS[unit]}"


def plural(count, word):
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def size_text(size):
    """The Vault Size window's text for a vault_size.VaultSize."""
    lines = [f"Stored on the host: about {readable(size.history_bytes + size.lfs_bytes)}", "",
             f"History ({plural(size.commits, 'commit')}, records and small files): {readable(size.history_bytes)}",
             f"CAD and other large files in Git LFS ({plural(size.lfs_files, 'file version')}): "
             f"{readable(size.lfs_bytes)}",
             f"Downloaded on this computer: {plural(size.downloaded_files, 'file version')}, "
             f"{readable(size.downloaded_bytes)}", "",
             "Every version of every file is counted once, however many commits use it. The host may also keep LFS "
             "files no commit uses any more; its own storage page shows those."]
    if not size.fetched:
        lines += ["", "The host couldn't be reached, so this is your copy as of your last Get Latest."]
    return "\n".join(lines)
