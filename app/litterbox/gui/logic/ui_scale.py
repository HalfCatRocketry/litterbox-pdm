"""
ui_scale.py - sizes that follow the display: Windows' scaling for each monitor (150% on most laptops and 4K
screens) times the person's Text size (View > Text size, remembered in settings.yaml as `text_size`).

CustomTkinter sizes its own widgets this way. The plain Tk parts (the lists, menus, tooltips, icons) don't, so
they take their sizes from here. Every size below is in pixels at 100%.
"""

TEXT_SIZES = (90, 100, 115, 130)        # percent
DEFAULT_TEXT_SIZE = 100


TABLE_FONT = 14                         # list text
TABLE_HEADING_FONT = 14
TABLE_ROW = 26                          # list row height
ICON = 16                               # status icons in the list
MENU_FONT = 14
SMALL_FONT = 12                         # the smallest text anywhere


def text_size(data):
    """The Text size setting (percent), from personal settings. Unknown values give the default."""
    value = data.get("text_size", DEFAULT_TEXT_SIZE) if isinstance(data, dict) else DEFAULT_TEXT_SIZE
    try:
        value = int(str(value).strip().rstrip("%"))
    except ValueError:
        return DEFAULT_TEXT_SIZE
    return value if value in TEXT_SIZES else DEFAULT_TEXT_SIZE


def step(current, direction):
    """The next Text size up (direction 1) or down (-1); stays put at either end. direction 0 resets."""
    if direction == 0:
        return DEFAULT_TEXT_SIZE
    sizes = list(TEXT_SIZES)
    index = sizes.index(current) if current in sizes else sizes.index(DEFAULT_TEXT_SIZE)
    return sizes[max(0, min(len(sizes) - 1, index + direction))]


def px(size, scale):
    """A size at 100%, in pixels at this scale (never below 1)."""
    return max(1, round(size * scale))


def font_px(size, scale):
    """A font size at this scale, as Tk wants it for a size in pixels (negative), never below SMALL_FONT."""
    return -px(max(size, SMALL_FONT), scale)


def sidebar_collapsed(window_width, scale):
    """Below this width (at 100%) the sidebar shows only its icons, to leave room for the list."""
    return window_width < px(1100, scale)
