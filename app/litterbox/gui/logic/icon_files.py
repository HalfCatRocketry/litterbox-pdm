"""
icon_files.py - which window icon to use (white or black) and finding its file.
"""

from pathlib import Path


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
