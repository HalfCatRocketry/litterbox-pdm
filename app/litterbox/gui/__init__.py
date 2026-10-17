"""
The Litterbox window (CustomTkinter). Start it with:  python app/main.py

The window is deliberately thin. What the buttons are allowed to do, and every text it shows, is worked out in
gui/logic/ (no window code, so it can be tested); the actions themselves are in parts/, workflows/, team/ and the
rest of the litterbox package; the git work is in git/.

    start.py          opens the window (or runs the build self-test)
    theme.py          colours
    scaling.py        making the plain Tk parts follow the display's scaling and the Text size
    window_chrome.py  title bar, icon, fade
    widgets/          small building blocks (ReleaseButton, menu bar, tooltips, icons, table sorting, ...)
    dialogs/          one small window per file
    windows/          the bigger non-modal windows (a part's Details pop-out, References, ECO, Import)
    screens/          My Tasks, ECOs and Team, shown in the main window from its sidebar
    panes/            a part's details, shown beside the parts list
    main_window/      the main window (App), one file per area
    logic/            decisions with no window code
"""
