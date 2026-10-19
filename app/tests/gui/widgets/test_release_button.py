"""Tests for gui/widgets/release_button.py. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes


class ReleaseButtonTests(unittest.TestCase):
    """Buttons act when the mouse button is released over them, not when it is pressed."""

    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        self.clicks = []
        base = self.gui.release_button.ReleaseButton.__mro__[1]
        base.invoke = lambda button: self.clicks.append(button)
        self.addCleanup(lambda: delattr(base, "invoke"))
        button = self.gui.release_button.ReleaseButton()
        button._state = "normal"
        button.winfo_rootx = lambda: 100
        button.winfo_rooty = lambda: 50
        button.winfo_width = lambda: 80
        button.winfo_height = lambda: 30
        self.button = button

    @staticmethod
    def at(x, y):
        from types import SimpleNamespace
        return SimpleNamespace(x_root=x, y_root=y)

    def test_pressing_alone_does_nothing(self):
        self.button._pressed(self.at(110, 60))
        self.assertEqual(self.clicks, [])

    def test_press_then_release_over_the_button_clicks_once(self):
        self.button._pressed(self.at(110, 60))
        self.button._released(self.at(120, 65))
        self.button._released(self.at(120, 65))              # a second release without a press does nothing
        self.assertEqual(len(self.clicks), 1)

    def test_releasing_away_from_the_button_cancels_the_click(self):
        self.button._pressed(self.at(110, 60))
        self.button._released(self.at(300, 65))
        self.assertEqual(self.clicks, [])
        self.button._released(self.at(120, 65))              # and the press is forgotten
        self.assertEqual(self.clicks, [])

    def test_a_missing_release_event_is_caught_by_the_mouse_check(self):
        state = {"down": True}
        self.gui.release_button.left_button_down = lambda: state["down"]
        self.button.winfo_pointerxy = lambda: (120, 65)
        self.button._pressed(self.at(110, 60))
        self.button._watch_mouse()                              # still held: nothing yet
        self.assertEqual(self.clicks, [])
        state["down"] = False
        self.button._watch_mouse()                              # let go, and Tk never sent the event
        self.assertEqual(len(self.clicks), 1)
        self.button._released(self.at(120, 65))                 # a late event doesn't click twice
        self.button._watch_mouse()
        self.assertEqual(len(self.clicks), 1)

    def test_mouse_check_cancels_when_let_go_off_the_button(self):
        self.gui.release_button.left_button_down = lambda: False
        self.button.winfo_pointerxy = lambda: (500, 500)
        self.button._pressed(self.at(110, 60))
        self.button._watch_mouse()
        self.assertEqual(self.clicks, [])

    def test_windows_saying_the_pointer_is_over_the_button_counts_even_if_tk_disagrees(self):
        # The edge-click bug: Tk's coordinates were off, so only the middle of a button worked.
        self.gui.release_button.pointer_inside = lambda widget: True
        self.button._pressed(self.at(110, 60))
        self.button._released(self.at(400, 400))
        self.assertEqual(len(self.clicks), 1)

    def test_a_click_at_the_very_edge_counts(self):
        self.gui.release_button.pointer_inside = lambda widget: None            # this system can't say: Tk's numbers decide
        for x, y in ((100, 50), (179, 79), (98, 49), (182, 82)):      # corners, and a few pixels of slack
            self.clicks.clear()
            self.button._pressed(self.at(x, y))
            self.button._released(self.at(x, y))
            self.assertEqual(len(self.clicks), 1, (x, y))

    def test_far_from_the_button_is_still_a_cancelled_click(self):
        self.gui.release_button.pointer_inside = lambda widget: False
        self.button._pressed(self.at(110, 60))
        self.button._released(self.at(190, 60))                  # 10 px past the right edge
        self.assertEqual(self.clicks, [])

    def test_a_disabled_button_never_arms(self):
        self.button._state = "disabled"
        self.button._pressed(self.at(110, 60))
        self.button._released(self.at(120, 65))
        self.assertEqual(self.clicks, [])


if __name__ == "__main__":
    unittest.main()
