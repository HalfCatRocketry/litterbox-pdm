"""
The Litterbox window (CustomTkinter). Start it with:  python app/main.py

The window is deliberately thin. What the buttons are allowed to do, and every text it shows, is worked out in
gui/logic/ (no window code, so it can be tested); the actions themselves are in parts/, workflows/, team/ and the
rest of the litterbox package; the git work is in git/.

    start.py          opens the window (or runs the build self-test)
    theme.py          colours
    window_chrome.py  title bar, icon, fade
    widgets/          small building blocks (ReleaseButton, table sorting, the part number cell editor)
    dialogs/          one small window per file
    windows/          the bigger non-modal windows (History, References, My Tasks, Team, Import)
    main_window/      the main window (App), one file per area
    logic/            decisions with no window code
"""
