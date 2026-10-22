"""
run_tests.py - runs Litterbox's tests in parallel: each test class in a process of its own, half as many at once as the
computer has cores (all of them made the computer lag), the slowest first (by the times of the last run, kept in tools/.test_times.json). The same tests
as `python -m unittest discover -s tests -t .` from app/, only sooner.

    python tools/run_tests.py                   the usual suite (the git tests are skipped on Windows)
    python tools/run_tests.py --git             everything, the git tests too (sets LITTERBOX_GIT_TESTS=1)
    python tools/run_tests.py tests.parts       only test classes whose names start with these
    python tools/run_tests.py --jobs 8          at most 8 at once (default: half the cores)

Each class runs in a fresh process, so tests that change os.environ or replace a module's function can't reach
another class; the git tests each make their own vault in a temporary folder, so they don't meet either. Prints
each failing class's output at the end, and exits with 1 if anything failed.
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
TIMES = Path(__file__).resolve().with_name(".test_times.json")
SUMMARY = re.compile(r"^Ran (\d+) tests? in", re.M)
COUNTS = re.compile(r"(failures|errors|skipped|expected failures|unexpected successes)=(\d+)")


def test_classes(prefixes=()):
    """'tests.parts.test_revise.ReviseFlow' and so on: every class that has tests, found the way unittest does."""
    sys.path.insert(0, str(APP))
    os.chdir(APP)
    found, todo = set(), [unittest.defaultTestLoader.discover("tests", top_level_dir=".")]
    while todo:
        suite = todo.pop()
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                todo.append(item)
            elif isinstance(item, unittest.TestCase):
                name = item.id().rsplit(".", 1)[0]
                if name.startswith("unittest.loader."):         # a module that failed to import: run it to see why
                    name = item.id().removeprefix("unittest.loader._FailedTest.")
                found.add(name)
    return sorted(name for name in found if not prefixes or name.startswith(tuple(prefixes)))


def run_one(name, env):
    started = time.monotonic()
    done = subprocess.run([sys.executable, "-m", "unittest", name], cwd=APP, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return name, done.returncode, done.stderr + done.stdout, time.monotonic() - started


def counts(output):
    """(tests run, {kind: count}) from unittest's last lines."""
    ran = SUMMARY.findall(output)
    return (int(ran[-1]) if ran else 0), {kind: int(n) for kind, n in COUNTS.findall(output.splitlines()[-1] if output.strip() else "")}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run Litterbox's tests in parallel.")
    parser.add_argument("prefixes", nargs="*", help="only test classes whose names start with these (tests.parts ...)")
    parser.add_argument("--git", action="store_true", help="run the git tests on Windows too (slow without this)")
    parser.add_argument("--jobs", type=int, default=max((os.cpu_count() or 4) // 2, 1), help="how many at once")
    args = parser.parse_args(argv)

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if args.git:
        env["LITTERBOX_GIT_TESTS"] = "1"
    names = test_classes(args.prefixes)
    try:
        times = json.loads(TIMES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        times = {}
    names.sort(key=lambda name: -times.get(name, 1e9))          # slowest first; unknown ones first of all
    print(f"Running {len(names)} test classes, {args.jobs} at once{' (git tests included)' if args.git else ''}...")

    started, failed, total, kinds = time.monotonic(), [], 0, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for count, future in enumerate(concurrent.futures.as_completed(
                [pool.submit(run_one, name, env) for name in names]), start=1):
            name, code, output, seconds = future.result()
            times[name] = round(seconds, 2)
            ran, found = counts(output)
            total += ran
            for kind, n in found.items():
                kinds[kind] = kinds.get(kind, 0) + n
            if code != 0:
                failed.append((name, output))
                print(f"  FAILED {name} ({seconds:.0f}s)")
            if count % 50 == 0:
                print(f"  {count} of {len(names)} done, {time.monotonic() - started:.0f}s")
    try:
        TIMES.write_text(json.dumps(times, indent=0, sort_keys=True), encoding="utf-8")
    except OSError:
        pass

    for name, output in failed:
        print("\n" + "=" * 100 + f"\n{name}\n" + "=" * 100)
        print("\n".join(line for line in output.splitlines() if not line.startswith("> ")))
    extra = ", ".join(f"{kind}={n}" for kind, n in sorted(kinds.items()))
    print(f"\nRan {total} tests in {time.monotonic() - started:.0f}s ({len(names)} classes). "
          + (f"FAILED: {len(failed)} classes" if failed else "OK") + (f" ({extra})" if extra else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
