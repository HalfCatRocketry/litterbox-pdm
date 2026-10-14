"""
start.py - opens the Litterbox window (or runs the build self-test). app/main.py calls main().
"""

import sys

import customtkinter as ctk

from litterbox import version
from litterbox.gui import window_chrome
from litterbox.gui.main_window import app
from litterbox.user import settings


def main():
    if "--self-test" in sys.argv:                       # used by the release pipeline; opens no window
        from litterbox.user import selftest
        after = sys.argv[sys.argv.index("--self-test") + 1:]
        sys.exit(selftest.run(after[0] if after else None, window_chrome.ASSETS_DIR))
    settings.append_log(f"Litterbox {version.display()} started")
    window_chrome.set_app_id()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app.App().mainloop()


if __name__ == "__main__":
    main()
