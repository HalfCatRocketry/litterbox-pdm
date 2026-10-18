"""The two-user vault with the helpers the New Part tests share. No tests here."""

import contextlib
import io
from pathlib import Path
from tests.support.vault_fixture import SKIP_ON_WINDOWS, TwoUserVault, git
from litterbox.cli import new_part as cli_new_part
from litterbox.parts import create_batch
from litterbox.git import runner


@SKIP_ON_WINDOWS
class CreateFixture(TwoUserVault):
    def assert_clean(self, repo):
        """Nothing left over: no changed or untracked files, and no commits waiting to be pushed."""
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(git(repo, "rev-list", "--count", "@{u}..HEAD"), "0")

    def record_names(self, repo):
        return sorted(p.name for p in (Path(repo) / "PN-logs").iterdir())

    def rival_pushes_first(self, rival_call, results):
        """A replacement for runner.run that lets Bea's creation land just before Alex's push."""
        real_run = runner.run
        state = {"done": False}

        def run(command, repo, quiet=False):
            if command[:2] == ["git", "push"] and not state["done"] and Path(repo) == self.a:
                state["done"] = True
                with self.user("Bea"):
                    results["bea"] = rival_call()
            return real_run(command, repo, quiet)

        return run

    def specs(self, count, **fields):
        return [create_batch.PartSpec(name=f"Part {n}", **fields) for n in range(1, count + 1)]

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_new_part.main([str(self.a), *args])
        return code, out.getvalue()
