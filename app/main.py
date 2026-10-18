"""
main.py - starts Litterbox.

Setup (once):   pip install -r requirements.txt     (from the repository's top folder)
Run:            python app/main.py
Self-test:      python app/main.py --self-test [result.txt]

This is also what PyInstaller builds into Litterbox.exe (see packaging/litterbox.spec). The program itself is the
litterbox package next to this file; docs/ARCHITECTURE.md describes how it is laid out.
"""

from litterbox.gui.start import main

if __name__ == "__main__":
    main()
