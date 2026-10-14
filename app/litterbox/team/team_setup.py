"""
team_setup.py - setting up a vault's team for the first time, with you as its Owner.
"""

import re
from pathlib import Path

from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.team import team_store


def setup_team(repo, name=None, email=None, roles=None):
    """Turn a vault with no people file into a managed one, with the person running this as its Owner.

    Needs the internet (the host has to tell Litterbox who you are). Two commits: the whoami file, then the
    people file. Returns the new Person."""
    repository.validate_repo(repo)
    if team_store.load(repo) is not None:
        raise team_model.PeopleError("This vault already has a team.")
    name = " ".join((name or repository.get_user(repo)).split())
    if not name:
        raise team_model.PeopleError("A name is required.")
    if email is None:
        try:
            email = runner.run(["git", "config", "user.email"], repo, quiet=True)
        except LitterboxError:
            email = ""
    remote.pull(repo)
    whoami = Path(repo) / layout.WHOAMI_FILE
    if not whoami.exists():
        whoami.parent.mkdir(parents=True, exist_ok=True)
        whoami.write_text("Litterbox takes a lock on this file to ask the host who you are. Leave it empty.\n",
                          encoding="utf-8")
        runner.run(["git", "add", "--", layout.WHOAMI_FILE], repo)
        runner.run(["git", "commit", "-m", "Team: add whoami file", "--", layout.WHOAMI_FILE], repo)
        remote.push_with_retry(repo)
    host_name = team_identity.probe_host_name(repo)
    person_id = re.sub(r"[^a-z0-9._-]+", "-", host_name.lower()).strip("-.")[:40] or "owner"
    if not team_model._ID_RE.match(person_id):
        person_id = "owner"
    directory = team_model.Directory([team_model.Person(person_id, name, email, [host_name], team_model.OWNER, [], True, [])],
                          list(roles if roles is not None else team_model.STANDARD_ROLES))
    team_store.save(repo, directory)
    try:
        runner.run(["git", "add", "--", layout.PEOPLE_FILE], repo)
        runner.run(["git", "commit", "-m", f"Team: set up with {name} as Owner", "--", layout.PEOPLE_FILE], repo)
        remote.push_with_retry(repo)
    except BaseException:
        try:
            runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
            runner.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", layout.PEOPLE_FILE], repo, quiet=True)
            (Path(repo) / layout.PEOPLE_FILE).unlink()
        except (LitterboxError, OSError):
            pass
        raise
    team_identity._write_cache(repo, host_name)
    return directory.people[0]
