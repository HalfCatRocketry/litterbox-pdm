"""Tests for gui/window_chrome.py: icon and fade. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from pathlib import Path
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace, FakeWindow


class WindowEffects(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())

    def test_a_window_starts_invisible_fades_in_and_fades_out_before_closing(self):
        window = FakeWindow()
        self.gui.window_chrome.set_window_icon(window)
        self.assertEqual(window.alpha, 0.0)                    # hidden while the icon is applied
        window.run_timers()                                    # the 0.4 s safety net reveals it
        rising = window.alphas[1:]
        self.assertEqual(rising[-1], 1.0)
        self.assertEqual(rising, sorted(rising))
        self.assertGreater(len(set(rising)), 3)                # a real fade, not a jump
        window.alphas.clear()
        window.destroy()                                       # the overridden destroy
        self.assertFalse(window.destroyed)                     # still on screen, fading
        window.destroy()                                       # a second close request is ignored
        window.run_timers()
        self.assertTrue(window.destroyed)
        self.assertEqual(window.alphas, sorted(window.alphas, reverse=True))
        self.assertEqual(window.alphas[-1], 0.0)

    def test_the_icon_is_put_back_after_customtkinter_resets_it(self):
        replace(self, self.gui.icon_files, "find_icon", lambda *a, **k: Path("litterbox.ico"))
        window = FakeWindow()
        self.gui.window_chrome.set_window_icon(window)
        window.run_timers()
        # once at creation, once when revealed, and again at 250, 500 and 900 ms
        self.assertGreaterEqual(window.icon_calls, 5)

    def test_the_main_windows_close_button_goes_through_the_fade(self):
        main, other = FakeWindow(), FakeWindow()
        self.gui.window_chrome.set_window_icon(main, main_window=True)
        self.gui.window_chrome.set_window_icon(other)
        self.assertIs(main.protocols["WM_DELETE_WINDOW"], main.destroy)
        self.assertFalse(hasattr(other, "protocols"))

    def test_closing_before_it_was_ever_shown_just_closes(self):
        window = FakeWindow()
        self.gui.window_chrome.set_window_icon(window)
        window.destroy()
        self.assertTrue(window.destroyed)


class Placed:
    """A window or its parent, as place_over sees it."""

    def __init__(self, x=0, y=0, width=0, height=0):
        self.x, self.y, self.width, self.height, self.geometries, self.minimum = x, y, width, height, [], None

    def winfo_rootx(self):
        return self.x

    def winfo_rooty(self):
        return self.y

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height

    def geometry(self, text):
        self.geometries.append(text)

    def minsize(self, width, height):
        self.minimum = (width, height)


class FittingOnScreen(unittest.TestCase):
    def setUp(self):
        self.chrome = load_gui_with_fakes(FakeBox()).window_chrome

    def place(self, area, scale, width=1060, height=800, parent=(0, 0, 1920, 1040)):
        window = Placed()
        replace(self, self.chrome, "work_area", lambda _w: area)
        replace(self, self.chrome, "window_scaling", lambda _w: scale)
        self.chrome.place_over(window, Placed(*parent), width, height, down=4)
        return window.geometries[-1]

    def test_a_window_that_fits_keeps_its_size(self):
        self.assertEqual(self.place((0, 0, 1920, 1040), 1.0), "1060x800+430+60")

    def test_a_window_too_tall_for_a_scaled_screen_shrinks_and_stays_on_it(self):
        # 1080p at 150%: 1040 pixels free above the taskbar is 693 at 100%, less the title bar and edges
        size, x, y = self.place((0, 0, 1920, 1040), 1.5).replace("+", " ").split()
        width, height = map(int, size.split("x"))
        self.assertEqual(height, 693 - self.chrome.TITLE_BAR - 2 * self.chrome.EDGE)
        self.assertLessEqual(int(y) + round(height * 1.5) + round(self.chrome.TITLE_BAR * 1.5), 1040)
        self.assertEqual(width, 1060)

    def test_the_minimum_size_never_exceeds_the_screen(self):
        window = Placed()
        replace(self, self.chrome, "work_area", lambda _w: (0, 0, 1280, 700))
        replace(self, self.chrome, "window_scaling", lambda _w: 1.25)
        self.chrome.min_size(window, 900, 620)
        self.assertEqual(window.minimum, (900, 560 - self.chrome.TITLE_BAR - 2 * self.chrome.EDGE))


if __name__ == "__main__":
    unittest.main()
