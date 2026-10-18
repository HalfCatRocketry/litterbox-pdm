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


if __name__ == "__main__":
    unittest.main()
