"""
icon_images.py - IconImages: the drawn icons (gui/logic/status_icons.py) and the Litterbox logo as Tk pictures,
made once per size and kept. Tk throws a picture away as soon as nothing in Python holds it, so every picture the
window shows lives here.
"""

import base64
import tkinter as tk

from litterbox.gui import theme
from litterbox.gui.logic import icon_files
from litterbox.gui.logic import png_images
from litterbox.gui.logic import status_icons


class IconImages:
    def __init__(self, master, assets_dir=None, icon_choice=icon_files.DEFAULT_ICON):
        self.master = master
        self.assets_dir, self.icon_choice = assets_dir, icon_choice
        self.cache = {}

    def clear(self):
        """Forget every picture (after the display scaling changes, they are made again at the new size)."""
        self.cache.clear()

    def _image(self, key, make):
        image = self.cache.get(key)
        if image is None:
            try:
                data = make()
            except Exception:
                data = None
            if not data:
                return None
            image = tk.PhotoImage(master=self.master, data=base64.b64encode(data).decode("ascii"))
            self.cache[key] = image
        return image

    def row(self, size, ticked, kind, busy=False, not_downloaded=False):
        """A part's first-column picture: tick box, status icon, badges."""
        return self._image(("row", size, ticked, kind, busy, not_downloaded),
                           lambda: status_icons.row_strip_png(size, ticked, kind, theme.ICON_COLORS, busy,
                                                              not_downloaded))

    def icon(self, name, size, color=theme.TEXT):
        return self._image(("icon", name, size, color), lambda: status_icons.icon_png(name, size, color))

    def status(self, kind, size):
        """A part status's icon on its own, in its colour."""
        shape = status_icons.STATUS.get(kind, status_icons.STATUS["error"])[0]
        return self.icon(shape, size, theme.ICON_COLORS.get(kind, theme.TEXT))

    def tick(self, size, ticked):
        return self._image(("tick", size, ticked),
                           lambda: status_icons.tick_png(size, ticked, theme.ICON_COLORS["box"], theme.ACCENT))

    def blank(self, width, height):
        """A see-through picture, to keep a column's width when a row has no icon."""
        return self._image(("blank", width, height), lambda: png_images.encode(width, height,
                                                                            bytearray(width * height * 4)))

    def logo(self, height):
        """The Litterbox logo (from its .ico file), `height` pixels tall, or None if the file can't be read."""
        def make():
            path = icon_files.find_icon(self.assets_dir, self.icon_choice) if self.assets_dir else None
            if path is None:
                return None
            decoded = png_images.decode(png_images.ico_png(path.read_bytes()) or b"")
            if decoded is None:
                return None
            return png_images.encode(*png_images.fit_height(*decoded, height))
        return self._image(("logo", height, self.icon_choice), make)
