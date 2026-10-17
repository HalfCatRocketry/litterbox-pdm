"""
theme.py - the window's colours, in one place (row colours of the parts list included).
"""



# Colors
BG = "#242424"                      # the window (CustomTkinter's dark background)


BG_PANEL = "#2b2b2b"


BG_BAR = "#1b1b1b"                  # the menu bar and the status bar


BG_SIDEBAR = "#202020"


BG_HEADING = "#1f1f1f"              # table headings


BG_HOVER = "#2f2f2f"                # a sidebar entry under the mouse


BG_CHOSEN = "#2c3e50"               # the sidebar entry that is showing


TEXT = "#e6e6e6"


ACCENT = "#1f6aa5"


GRAY = "#3a3a3a"


GRAY_HOVER = "#4a4a4a"


TICK_BG = "#4d4d4d"                 # a ticked (selected) row in the parts list: lighter than the list background


GREEN, GREEN_HOVER = "#2e8b57", "#256f45"


TEAL, TEAL_HOVER = "#2f7d8c", "#256673"


RED, RED_HOVER = "#8b3a3a", "#6f2e2e"


PURPLE, PURPLE_HOVER = "#6b4fa3", "#573f87"


MUTED = "#9a9a9a"


WARN = "#e5c07b"


BANNER_YELLOW = "#d9a520"


GREEN_TEXT = "#5fd38d"


ERROR = "#e06c75"


# Row colors in the list, by the "kind" of status (see litterbox_engine.PartStatus)
ROW_COLORS = {
    "ok": "#e6e6e6",          # available
    "mine": "#5fd38d",        # checked out by you
    "theirs": "#f0a35e",      # checked out by someone else
    "unclaimed": "#e5c07b",   # modified, and nobody has it checked out
    "stray": "#e5c07b",       # modified without being checked out
    "missing": "#e06c75",     # no longer used for parts (a part that is not downloaded keeps its colour)
    "released": "#6cb6ff",
    "cots": "#4fc1c9",        # purchased part
    "void": "#7a7a7a",
    "pending": "#b39ddb",     # waiting for sign-off
    "error": "#e06c75",
}


# The status icons (gui/logic/status_icons.py): each kind's colour, the tick box, and the badges.
ICON_COLORS = dict(ROW_COLORS, box="#949a9f", accent=ACCENT, busy=BANNER_YELLOW, cloud="#9ecbff")
