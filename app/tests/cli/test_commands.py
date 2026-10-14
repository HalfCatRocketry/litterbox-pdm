"""Tests for python -m litterbox <command>: which commands exist and how they are handed their options."""

import contextlib
import importlib
import io
import sys
import unittest
from unittest import mock

from litterbox import cli


class Commands(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(sys, "argv", ["litterbox", *argv]):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_no_command_or_help_lists_the_commands(self):
        for argv in ((), ("--help",), ("-h",)):
            code, text = self.run_cli(*argv)
            self.assertEqual(code, 0)
            for command in cli.COMMANDS:
                self.assertIn(command, text)

    def test_an_unknown_command_says_so(self):
        code, text = self.run_cli("bogus")
        self.assertEqual(code, 2)
        self.assertIn("Unknown command: bogus", text)

    def test_every_command_has_a_main_that_takes_its_options(self):
        for command, name in cli.COMMANDS.items():
            module = importlib.import_module(name)
            self.assertTrue(callable(module.main), command)

    def test_the_command_gets_the_rest_of_the_line(self):
        seen = []
        module = importlib.import_module(cli.COMMANDS["scan"])
        with mock.patch.object(module, "main", lambda argv, prog=None: seen.append((argv, prog)) or 3):
            code, _ = self.run_cli("scan", "C:/old", "--no-hash")
        self.assertEqual((code, seen), (3, [(["C:/old", "--no-hash"], "python -m litterbox scan")]))

    def test_help_shows_how_to_call_each_command(self):
        for command in cli.COMMANDS:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                cli.main([command, "--help"])
            self.assertIn(f"usage: python -m litterbox {command}", out.getvalue())


if __name__ == "__main__":
    unittest.main()
