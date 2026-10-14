"""
Tests for jobs.py (the background job queue and the banner's states) and the gui_logic pieces that go with it:
labels, the busy marks, and the advice shown for an error.
"""

import threading
import unittest


from litterbox.gui.logic import action_rules
from litterbox.gui.logic import checkin_text
from litterbox.gui.logic import error_text
from litterbox.gui.logic import job_text
from litterbox.jobs import job_queue as jobs
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError, NothingToSaveError
from tests.support.gui_source import gui_source


class Collector:
    """Stands in for the window: remembers what was delivered, and finishes each job like the window does."""

    def __init__(self):
        self.outcomes = []
        self.queue = jobs.JobQueue(deliver=self.deliver)

    def deliver(self, outcome):
        self.outcomes.append(outcome)

    def finish_all(self):
        for outcome in list(self.outcomes):
            self.queue.finished(outcome.job)


def wait_for(condition, timeout=5.0):
    end = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if condition():
            return True
        end.wait(0.01)
    return False


class Queue(unittest.TestCase):
    def test_jobs_run_one_at_a_time_in_the_order_they_were_added(self):
        c, order = Collector(), []
        gate = threading.Event()

        def slow():
            gate.wait(5)
            order.append("first")

        first = c.queue.submit(jobs.Job("one", slow))
        c.queue.submit(jobs.Job("two", lambda: order.append("second")))
        c.queue.submit(jobs.Job("three", lambda: order.append("third")))
        self.assertTrue(wait_for(lambda: first.state == "running"))
        self.assertEqual(order, [])                                        # the others are waiting
        self.assertEqual(c.queue.waiting_count(), 2)
        gate.set()
        self.assertTrue(wait_for(lambda: len(c.outcomes) == 3))
        self.assertEqual(order, ["first", "second", "third"])

    def test_results_and_errors_are_delivered(self):
        c = Collector()

        def broken():
            raise LitterboxError("push failed")

        def surprise():
            raise ValueError("boom")

        def nothing():
            raise NothingToSaveError("same")

        c.queue.submit(jobs.Job("a", lambda: 42))
        c.queue.submit(jobs.Job("b", broken))
        c.queue.submit(jobs.Job("c", surprise))
        c.queue.submit(jobs.Job("d", nothing))
        self.assertTrue(wait_for(lambda: len(c.outcomes) == 4))
        a, b, cc, d = c.outcomes
        self.assertEqual((a.result, a.error), (42, None))
        self.assertEqual(b.error, "push failed")
        self.assertIn("Unexpected error", cc.error)
        self.assertIsInstance(d.error, NothingToSaveError)

    def test_a_part_stays_busy_until_the_window_has_shown_the_result(self):
        c = Collector()
        job = c.queue.submit(jobs.Job("Checking in 2 parts", lambda: None, parts=(PN("HCR", 1, 1), "HCR-00002-001")))
        self.assertEqual(c.queue.pending_parts(), {"HCR-00001-001": "Checking in 2 parts",
                                                   "HCR-00002-001": "Checking in 2 parts"})
        self.assertTrue(wait_for(lambda: len(c.outcomes) == 1))
        self.assertEqual(len(c.queue.pending_parts()), 2)                  # done, but not shown yet
        self.assertFalse(c.queue.working())
        self.assertTrue(c.queue.active())
        c.queue.finished(job)
        self.assertEqual(c.queue.pending_parts(), {})
        self.assertFalse(c.queue.active())

    def test_only_the_newest_waiting_refresh_is_kept(self):
        c, ran = Collector(), []
        gate = threading.Event()
        long = c.queue.submit(jobs.Job("long", lambda: gate.wait(5)))
        self.assertTrue(wait_for(lambda: long.state == "running"))
        for n in range(4):
            c.queue.submit(jobs.Job("refresh", lambda n=n: ran.append(n), kind="refresh"))
        self.assertEqual(c.queue.waiting_count(), 1)
        gate.set()
        self.assertTrue(wait_for(lambda: len(c.outcomes) == 2))
        self.assertEqual(ran, [3])

    def test_wait_idle_returns_when_everything_is_finished(self):
        c = Collector()
        c.queue.submit(jobs.Job("x", lambda: None))
        self.assertTrue(wait_for(lambda: len(c.outcomes) == 1))
        self.assertFalse(c.queue.wait_idle(0.05))                          # still waiting to be shown
        c.finish_all()
        self.assertTrue(c.queue.wait_idle(1))


class Banner(unittest.TestCase):
    def test_ready_working_and_error(self):
        c = Collector()
        self.assertEqual((c.queue.banner().kind, c.queue.banner().title), (jobs.READY, "Ready"))
        gate = threading.Event()
        first = c.queue.submit(jobs.Job("Checking in 12 parts", lambda: gate.wait(5)))
        c.queue.submit(jobs.Job("Getting the latest", lambda: None))
        self.assertTrue(wait_for(lambda: first.state == "running"))
        banner = c.queue.banner()
        self.assertEqual((banner.kind, banner.title), (jobs.WORKING, "Working"))
        self.assertEqual(banner.detail, "Checking in 12 parts - 1 more waiting")
        gate.set()
        self.assertTrue(wait_for(lambda: len(c.outcomes) == 2))
        c.finish_all()
        self.assertEqual(c.queue.banner().kind, jobs.READY)

    def test_an_error_stays_red_until_dismissed_and_shows_how_many(self):
        c = Collector()
        c.queue.add_error("Checking in", "push failed", "try again")
        c.queue.add_error("Voiding", "no network", "check your connection")
        banner = c.queue.banner()
        self.assertEqual((banner.kind, banner.title, banner.errors), (jobs.ERROR, "Error", 2))
        self.assertEqual(banner.detail, "2 problems")
        c.queue.submit(jobs.Job("Getting the latest", lambda: None))
        self.assertTrue(wait_for(lambda: len(c.outcomes) == 1))
        c.finish_all()
        self.assertEqual(c.queue.banner().kind, jobs.ERROR)                # a good job does not clear it
        c.queue.dismiss_errors()
        self.assertEqual(c.queue.banner().kind, jobs.READY)

    def test_the_error_banner_says_when_work_continues(self):
        c = Collector()
        gate = threading.Event()
        c.queue.add_error("x", "bad")
        job = c.queue.submit(jobs.Job("Refreshing the list", lambda: gate.wait(5)))
        self.assertTrue(wait_for(lambda: job.state == "running"))
        self.assertEqual(c.queue.banner().detail, "1 problem - still working: Refreshing the list")
        gate.set()


class Logic(unittest.TestCase):
    def test_job_labels(self):
        self.assertEqual(job_text.job_label("checkin", 1), "Checking in 1 part")
        self.assertEqual(job_text.job_label("void", 12), "Voiding 12 parts")
        self.assertEqual(job_text.job_label("nonsense", 2), "Working on 2 parts")

    def test_busy_text_in_the_status_column(self):
        self.assertEqual(job_text.busy_state_text("Checked out by you", "Checking in 2 parts"),
                         "⏳ checking in 2 parts...")

    def test_advice_covers_the_usual_problems_and_always_says_something(self):
        cases = {
            "fatal: unable to access 'https://dev.azure.com/x': Could not resolve host": "internet connection",
            "remote: Authentication failed for 'https://x'": "sign-in",
            "HCR-00001-001 is already checked out by Bea.": "Someone else",
            "Your changes are saved in the vault, but some files could not be unlocked": "Check In on the same parts",
            "Unexpected error: KeyError('x')": "send the log",
            "something nobody has seen before": "Refresh",
        }
        for message, expected in cases.items():
            self.assertIn(expected, error_text.error_advice(message), message)

    def test_the_report_lists_each_problem_with_what_to_do(self):
        notes = [jobs.ErrorNote("Checking in 2 parts", "push failed", "try again"),
                 jobs.ErrorNote("Voiding", "no network", "check your connection")]
        text = error_text.error_report_text(notes)
        for part in ("Checking in 2 parts", "push failed", "What to do: try again", "Voiding", "no network"):
            self.assertIn(part, text)

    def test_parts_with_a_job_in_progress_are_skipped_but_can_still_be_looked_at(self):
        from litterbox.parts.part_status import PartStatus
        pn1, pn2 = PN("HCR", 1, 1), PN("HCR", 2, 1)
        rows = {pn1: PartStatus(pn1, "a", "in_work", "mine", "mine"), pn2: PartStatus(pn2, "b", "in_work", "mine", "mine")}
        pending = {str(pn1): "Checking in 1 part"}
        plan = action_rules.plan_action("checkin", [pn1, pn2], rows, pending)
        self.assertEqual(plan.targets, [pn2])
        self.assertEqual(plan.skipped, [(pn1, "busy: checking in 1 part")])
        self.assertEqual(action_rules.plan_action("open", [pn1], rows, pending).targets, [pn1])
        states = action_rules.button_states([pn1], [], rows, pending)
        self.assertFalse(states["Check In"])
        self.assertFalse(states["Undo Checkout"])
        self.assertTrue(states["Open"])
        self.assertTrue(action_rules.button_states([pn2], [], rows, pending)["Check In"])

    def test_the_caution_and_the_open_warning_say_to_wait_for_ready(self):
        self.assertIn("Ready", checkin_text.CHECKIN_CAUTION)
        self.assertIn("banner", checkin_text.open_while_busy_text(PN("HCR", 7, 1), "Checking in 2 parts"))


class Wiring(unittest.TestCase):
    """The window source keeps its promises (the window itself can't be built in a test)."""

    @classmethod
    def setUpClass(cls):
        cls.source = gui_source()

    def test_the_banner_and_its_buttons_exist(self):
        for text in ("self.banner_title", 'text="Details..."', 'text="Dismiss"', "class ErrorDetailsWindow",
                     "jobs.READY: theme.GREEN", "jobs.WORKING: theme.BANNER_YELLOW", "jobs.ERROR: theme.RED"):
            self.assertIn(text, self.source)

    def test_closing_with_work_in_the_queue_asks_first(self):
        self.assertIn('self.protocol("WM_DELETE_WINDOW", self._on_close)', self.source)
        self.assertIn("Litterbox is still working", self.source)

    def test_the_check_in_prompt_carries_the_caution_and_batches_pass_their_parts(self):
        self.assertIn("checkin_text.CHECKIN_CAUTION", self.source)
        self.assertIn("label=job_text.job_label(action, len(targets)), parts=targets", self.source)

    def test_a_refresh_is_collapsible_and_no_task_is_refused_for_being_busy(self):
        self.assertIn('kind="refresh"', self.source)
        self.assertNotIn("Still working on the last request", self.source)


if __name__ == "__main__":
    unittest.main()
