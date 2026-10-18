"""Tests for cad/solidworks/sw_process.py: making sure a SolidWorks Litterbox started exits."""

import unittest
from litterbox.cad.solidworks import sw_backend
from litterbox.cad.solidworks import sw_process


class ClosingSolidWorks(unittest.TestCase):
    """The SolidWorks we start must really be gone afterwards, or Open later lands in an invisible window."""

    def test_waits_for_a_slow_exit_without_ending_it(self):
        alive = iter([True, True, False])
        ended = []
        result = sw_process.wait_for_exit(42, alive=lambda pid: next(alive), kill=ended.append, sleep=lambda s: None)
        self.assertEqual((result, ended), ("exited", []))

    def test_ends_a_process_that_will_not_exit(self):
        ended, notes = [], []
        result = sw_process.wait_for_exit(42, timeout=1, alive=lambda pid: True, kill=ended.append,
                                        sleep=lambda s: None, log=notes.append)
        self.assertEqual((result, ended), ("ended", [42]))
        self.assertTrue(notes)

    def test_already_gone_needs_no_waiting(self):
        self.assertEqual(sw_process.wait_for_exit(42, alive=lambda pid: False, kill=lambda p: 1 / 0), "exited")

    def test_only_a_solidworks_we_started_is_exited_and_waited_for(self):
        calls = []

        class App:
            def GetProcessID(self):
                return 77

            def ExitApp(self):
                calls.append("exit")

        original = sw_process.wait_for_exit
        sw_process.wait_for_exit = lambda pid, **kw: calls.append(("wait", pid))
        try:
            backend = sw_backend.SolidWorksBackend()
            backend._sw, backend._started_by_us = App(), True
            backend.close()
            self.assertEqual(calls, ["exit", ("wait", 77)])
            calls.clear()
            backend._sw, backend._started_by_us, backend._pid = App(), True, 55     # learned at start-up: preferred
            backend.close()
            self.assertEqual(calls, ["exit", ("wait", 55)])
            calls.clear()
            backend._sw, backend._started_by_us = App(), False          # the user's own SolidWorks: hands off
            backend.close()
            self.assertEqual(calls, [])
        finally:
            sw_process.wait_for_exit = original


class FindingTheProcess(unittest.TestCase):
    def test_solidworks_own_answer_is_used(self):
        class App:
            def GetProcessID(self):
                return 9
        self.assertEqual(sw_process.own_process_id(App(), {1}), 9)

    def test_otherwise_the_one_new_process_is_used(self):
        class App:
            def GetProcessID(self):
                raise RuntimeError
        original = sw_process.solidworks_pids
        try:
            sw_process.solidworks_pids = lambda: {1, 8}
            self.assertEqual(sw_process.own_process_id(App(), {1}), 8)
            sw_process.solidworks_pids = lambda: {1, 8, 9}                     # two new: can't tell which
            self.assertIsNone(sw_process.own_process_id(App(), {1}))
        finally:
            sw_process.solidworks_pids = original

    def test_the_wait_is_five_seconds(self):
        self.assertEqual(sw_process.EXIT_WAIT_SECONDS, 5.0)


if __name__ == "__main__":
    unittest.main()
