"""
text_size.py - View > Text size (90% to 130%, Ctrl+= / Ctrl+- / Ctrl+0), remembered in settings.yaml, and keeping
the plain Tk parts of the window (the list, its icons, the menus) the right size when the scaling changes: a new
Text size, or the window moved to a monitor with different scaling.
"""

from litterbox.gui import scaling
from litterbox.gui.logic import ui_scale
from litterbox.user import settings


class TextSize:
    """Text size and display scaling (a part of the main window, App)."""

    def _bind_text_size_keys(self):
        for keys, direction in (("<Control-equal>", 1), ("<Control-plus>", 1), ("<Control-KP_Add>", 1),
                                ("<Control-minus>", -1), ("<Control-KP_Subtract>", -1), ("<Control-0>", 0)):
            self.bind(keys, lambda event, direction=direction: self.step_text_size(direction))

    def step_text_size(self, direction):
        self.apply_text_size(ui_scale.step(self.text_size, direction))

    def apply_text_size(self, percent):
        """Make everything bigger or smaller and remember the choice."""
        if percent == self.text_size:
            return
        self.text_size = percent
        self.settings["text_size"] = percent
        settings.save(self.settings)
        scaling.set_text_size(percent)
        self._say(f"Text size {percent}%")
        self._rescale_soon()

    def _rescale_soon(self):
        if getattr(self, "_rescale_job", None) is None:
            self._rescale_job = self.after(200, self._rescale)

    def _rescale(self):
        """Draw the plain Tk parts again at the current scaling."""
        self._rescale_job = None
        scale = scaling.scale_of(self)
        if abs(scale - getattr(self, "scale", 0)) < 0.01:
            return
        self.scale = scale
        scaling.style_tables(scale)
        self.icons.clear()
        self._forget_measures()
        self._set_up_columns()
        self._refresh_nav_images()
        self.menu_bar.set_logo(self.icons.logo(self._px(18)))
        self.set_sidebar_collapsed(self.sidebar_collapsed)
        self._render()
        self.pane_pn = None
        self._show_details()
