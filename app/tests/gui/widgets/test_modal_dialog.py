"""Tests for gui/widgets/modal_dialog.py, the base of every dialog. The window itself is replaced by stand-ins
(tests/support/gui_fakes.py)."""

import unittest
from types import SimpleNamespace

from tests.support.gui_fakes import FakeBox, load_gui_with_fakes


class ModalDialogTests(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        self.calls = []

    def dialog(self, cls=None, focus=None):
        cls = cls or self.gui.modal_dialog.ModalDialog
        d = cls.__new__(cls)
        d.grab_set = lambda: self.calls.append("grab")
        d.focus_force = lambda: self.calls.append("focus")
        if focus:
            d.FOCUS = focus
            setattr(d, focus, SimpleNamespace(focus_set=lambda: self.calls.append(focus)))
        return d

    def test_grab_takes_the_focus(self):
        self.dialog()._grab()
        self.assertEqual(self.calls, ["grab", "focus"])

    def test_focus_puts_the_cursor_in_the_named_box(self):
        self.dialog(focus="entry")._grab()
        self.assertEqual(self.calls, ["grab", "focus", "entry"])

    def test_a_window_already_gone_is_not_an_error(self):
        d = self.dialog()

        def gone():
            raise self.gui.modal_dialog.tk.TclError("window was deleted")
        d.grab_set = gone
        d._grab()                                       # no exception
        self.assertEqual(self.calls, [])

    def test_show_waits_then_returns_the_answer(self):
        d = self.dialog()
        d.wait_window = lambda window: (self.calls.append("waited"), setattr(d, "result", "OK"))
        self.assertEqual(d.show(), "OK")
        self.assertEqual(self.calls, ["waited"])

    def test_the_dialogs_use_it(self):
        g = self.gui
        for cls, focus in ((g.confirm_dialogs.ConfirmDialog, None), (g.text_input.ReasonDialog, "entry"),
                           (g.new_part_dialog.NewPartDialog, "name_entry"), (g.clone_dialog.CloneDialog, "entry"),
                           (g.request_dialog.WorkflowRequestDialog, None), (g.import_window.ImportWindow, None)):
            self.assertTrue(issubclass(cls, g.modal_dialog.ModalDialog), cls.__name__)
            self.assertEqual(cls.FOCUS, focus, cls.__name__)

    def test_discard_dialog_keeps_its_own_answer(self):
        d = self.dialog(self.gui.confirm_dialogs.DiscardDialog)
        d.wait_window = lambda window: setattr(d, "discard", True)
        self.assertIs(d.show(), True)


if __name__ == "__main__":
    unittest.main()
