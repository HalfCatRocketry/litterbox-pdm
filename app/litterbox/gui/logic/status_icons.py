"""
status_icons.py - the little pictures in the parts list and the sidebar: one icon per part status (each a different
shape, so colour is never the only clue), the tick box, the "busy" and "not downloaded" badges, and the sidebar's
icons. They are drawn (see icon_drawing.py) at whatever size the display needs, as PNG data for Tk.

The colours are passed in by the window (gui/theme.py), so this file holds only shapes and words.
"""

import math

from litterbox.gui.logic import icon_drawing as draw

# Which shape each part status (PartStatus.kind) gets, and what it means, for the tooltip and the legend.
STATUS = {
    "ok":        ("ring",     "Checked in", "Nobody has it checked out. Check it out to change it."),
    "mine":      ("pencil",   "Checked out by you", "You can change it. Check it in when you are done."),
    "theirs":    ("padlock",  "Checked out by someone else", "Someone else is changing it. You can open it to look."),
    "unclaimed": ("warning",  "Changed, not checked out", "Its files were changed on this computer without "
                                                          "checking it out."),
    "stray":     ("warning",  "Needs attention", "Its files don't match its record (see Status in the details)."),
    "released":  ("check",    "Released", "Frozen. Revise it to make a new revision."),
    "cots":      ("nut",      "COTS", "A purchased part."),
    "void":      ("ban",      "Void", "No longer used."),
    "pending":   ("clock",    "Waiting for sign-off", "A request is waiting for sign-offs (see Workflows)."),
    "missing":   ("cross",    "Missing", "Its files are missing."),
    "error":     ("cross",    "Unreadable", "Its record can't be read."),
}


BADGES = (("busy", "Litterbox is working on it", "A job is queued or running for this part."),
          ("cloud", "Not downloaded", "Its files download when you check it out or open it."))


def status_label(kind):
    return STATUS.get(kind, STATUS["error"])[1]


def legend():
    """[(shape, title, explanation)] for Help > Status icons."""
    seen, rows = set(), []
    for _kind, (shape, title, text) in STATUS.items():
        if (shape, title) not in seen:
            seen.add((shape, title))
            rows.append((shape, title, text))
    return rows + list(BADGES)


# -- the shapes, in a square from 0 to 1 -----------------------------------------------------------------------------

def _shape(name):
    if name == "ring":
        return draw.ring(0.5, 0.5, 0.31, 0.12)
    if name == "pencil":
        return draw.union(draw.segment(0.36, 0.64, 0.74, 0.26, 0.2),
                          draw.polygon([(0.15, 0.85), (0.21, 0.6), (0.4, 0.79)]))
    if name == "padlock":
        shackle = draw.subtract(draw.ring(0.5, 0.42, 0.17, 0.1), draw.box(0.5, 0.62, 0.3, 0.16))
        body = draw.subtract(draw.box(0.5, 0.66, 0.28, 0.21, 0.05), draw.circle(0.5, 0.64, 0.055))
        return draw.union(shackle, body)
    if name == "warning":
        triangle = draw.grow(draw.polygon([(0.5, 0.15), (0.87, 0.82), (0.13, 0.82)]), 0.035)
        mark = draw.union(draw.segment(0.5, 0.38, 0.5, 0.57, 0.1), draw.circle(0.5, 0.7, 0.055))
        return draw.subtract(triangle, mark)
    if name == "check":
        return draw.subtract(draw.circle(0.5, 0.5, 0.41),
                             draw.polyline([(0.3, 0.52), (0.44, 0.66), (0.7, 0.37)], 0.11))
    if name == "nut":
        return draw.subtract(draw.regular_polygon(0.5, 0.5, 0.42, 6, math.pi / 6), draw.circle(0.5, 0.5, 0.16))
    if name == "ban":
        return draw.union(draw.ring(0.5, 0.5, 0.34, 0.11), draw.segment(0.27, 0.27, 0.73, 0.73, 0.11))
    if name == "clock":
        return draw.union(draw.ring(0.5, 0.5, 0.35, 0.1), draw.segment(0.5, 0.5, 0.5, 0.3, 0.09),
                          draw.segment(0.5, 0.5, 0.65, 0.58, 0.09))
    if name == "cross":
        return draw.subtract(draw.circle(0.5, 0.5, 0.41),
                             draw.union(draw.segment(0.36, 0.36, 0.64, 0.64, 0.11),
                                        draw.segment(0.64, 0.36, 0.36, 0.64, 0.11)))
    if name == "cloud":
        return draw.union(draw.circle(0.36, 0.58, 0.17), draw.circle(0.56, 0.47, 0.22), draw.circle(0.74, 0.62, 0.14),
                          draw.box(0.55, 0.68, 0.24, 0.1, 0.08))
    if name == "busy":
        return draw.circle(0.5, 0.5, 0.4)
    if name == "list":
        return draw.union(*[draw.segment(0.38, y, 0.82, y, 0.1) for y in (0.28, 0.5, 0.72)],
                          *[draw.circle(0.2, y, 0.07) for y in (0.28, 0.5, 0.72)])
    if name == "tasks":
        board = draw.subtract(draw.box(0.5, 0.55, 0.32, 0.37, 0.07), draw.box(0.5, 0.55, 0.22, 0.27, 0.03))
        return draw.union(board, draw.box(0.5, 0.18, 0.15, 0.07, 0.03),
                          draw.polyline([(0.37, 0.56), (0.47, 0.66), (0.65, 0.45)], 0.09))
    if name == "document":
        page = draw.polygon([(0.22, 0.1), (0.6, 0.1), (0.8, 0.3), (0.8, 0.9), (0.22, 0.9)])
        lines = draw.union(*[draw.segment(0.34, y, 0.68, y, 0.07) for y in (0.45, 0.6, 0.75)])
        return draw.subtract(page, draw.union(lines, draw.polygon([(0.58, 0.06), (0.86, 0.06), (0.86, 0.34)])))
    if name == "team":
        return draw.union(draw.circle(0.36, 0.32, 0.14), draw.box(0.36, 0.72, 0.24, 0.18, 0.15),
                          draw.circle(0.7, 0.36, 0.11), draw.box(0.72, 0.73, 0.18, 0.16, 0.12))
    raise KeyError(name)


SHAPES = ("ring", "pencil", "padlock", "warning", "check", "nut", "ban", "clock", "cross", "cloud", "busy", "list",
          "tasks", "document", "team")


def icon_png(name, size, color):
    """One shape, `size` pixels square, as PNG bytes."""
    picture = draw.Drawing(size)
    picture.paint(_shape(name), color)
    return picture.png()


OUTLINE = "#1b1b1b"                 # the dark rim around a badge, so it stands out from the icon under it


TICK_GAP = 0.45                     # space between the tick box and the status icon, in icon heights


def strip_width(size):
    """How wide the parts list's first column picture is: tick box, gap, status icon."""
    return round(size * (2 + TICK_GAP))


def tick_part(picture, ticked, box_color, accent, left=0.0):
    outer = draw.box(0.5, 0.5, 0.41, 0.41, 0.12)
    if ticked:
        picture.paint(outer, accent, left=left)
        picture.paint(draw.polyline([(0.29, 0.52), (0.44, 0.67), (0.71, 0.36)], 0.12), "#ffffff", left=left)
    else:
        picture.paint(draw.subtract(outer, draw.box(0.5, 0.5, 0.3, 0.3, 0.05)), box_color, left=left)


def row_strip_png(size, ticked, kind, colors, busy=False, not_downloaded=False):
    """The picture in a part's first column: its tick box, then its status icon with any badges.

    colors: {"box", "accent", "busy", "cloud"} plus a colour for each status kind."""
    picture = draw.Drawing(size, strip_width(size))
    tick_part(picture, ticked, colors["box"], colors["accent"])
    left = 1 + TICK_GAP
    shape = STATUS.get(kind, STATUS["error"])[0]
    picture.paint(_shape(shape), colors.get(kind, colors["box"]), left=left)
    if not_downloaded:
        badge = draw.placed(_shape("cloud"), 0.55, 0.5, 0.48)
        picture.paint(draw.grow(badge, 0.06), OUTLINE, left=left)
        picture.paint(badge, colors["cloud"], left=left)
    if busy:
        badge = draw.placed(_shape("busy"), 0.5, 0.52, -0.02)
        picture.paint(draw.grow(badge, 0.06), OUTLINE, left=left)
        picture.paint(badge, colors["busy"], left=left)
    return picture.png()


def tick_png(size, ticked, box_color, accent):
    """Just a tick box (the heading of the tick column, and other lists)."""
    picture = draw.Drawing(size)
    tick_part(picture, ticked, box_color, accent)
    return picture.png()


def badge_png(name, size, color):
    """A badge on its own, for the legend: drawn like on a row, without the icon under it."""
    picture = draw.Drawing(size)
    picture.paint(_shape(name), color)
    return picture.png()
