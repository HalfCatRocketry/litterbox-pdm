"""
The check-out and check-in tests again, on a vault that stores its CAD files through (fake) Git LFS like a real one,
and once more on a copy that downloads on demand: the actions must behave the same. They need Linux, macOS or WSL.
"""

import unittest

from tests.support.vault_fixture import PART, PRT, REC
from tests.parts.test_checkin_flow import CheckInFlow
from tests.parts.test_checkout_flow import CheckOutFlow

from litterbox.git import read_only
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import downloads
from litterbox.parts import get_latest


class CheckOutFlowWithLFS(CheckOutFlow):
    LFS = True


class CheckInFlowWithLFS(CheckInFlow):
    LFS = True


class CheckOutFlowOnDemand(CheckOutFlow):
    ON_DEMAND = True


class CheckInFlowOnDemand(CheckInFlow):
    ON_DEMAND = True

    def test_checkin_uploads_logs_and_unlocks(self):
        """As in CheckInFlow, except that Bea never downloaded the part, so Get Latest leaves it as a pointer
        (download on demand); opening it downloads the new version."""
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            self.assertTrue(checkin.checkin(self.a, PART, "Added fillet").uploaded)
        with self.user("Bea"):
            self.assertEqual(sorted(get_latest.get_latest(self.b)), sorted([PRT, REC]))
            self.assertTrue(read_only.is_pointer(self.b / PRT))
            downloads.download_for_open(self.b, PART, "A")
            self.assertEqual((self.b / PRT).read_bytes(), b"version 2")


del CheckOutFlow, CheckInFlow           # run only the variants here (the originals run in their own files)


if __name__ == "__main__":
    unittest.main()
