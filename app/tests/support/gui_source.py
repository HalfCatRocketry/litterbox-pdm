"""The window's code as text, for tests that check the window calls something (no window is opened). No tests here."""

from pathlib import Path

GUI_DIR = Path(__file__).resolve().parents[2] / "litterbox" / "gui"


def gui_source():
    """Every window module (litterbox/gui, without gui/logic) joined into one text."""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(GUI_DIR.rglob("*.py"))
                     if "logic" not in path.relative_to(GUI_DIR).parts)
