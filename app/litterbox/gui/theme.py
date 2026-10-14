"""
theme.py - the window's colours, in one place (row colours of the parts list included).
"""



# Colors
BG_PANEL = "#2b2b2b"


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
    "missing": "#e06c75",     # not downloaded
    "released": "#6cb6ff",
    "cots": "#4fc1c9",        # purchased part
    "void": "#7a7a7a",
    "error": "#e06c75",
}
