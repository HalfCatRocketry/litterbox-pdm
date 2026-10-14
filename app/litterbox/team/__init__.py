"""
Who may do what: the team file, identity, permissions, signed commits.

people.py - who is on the team, what each person may do, and who the current user is.

THE FILE   .litterbox/people.yaml lives in the vault, so everybody gets the same copy through Git:

    roles: [Responsible Engineer, Manufacturing, Quality]     roles this org uses (Admins edit the list)
    people:
    - id: alex                      short, permanent, lowercase
      name: Alex Smith
      email: alex@example.com
      host_names: [alexsmith]       the names your Git host may report for this person (see "Who am I?")
      access: owner                 owner (exactly one) | admin | member
      roles: [Responsible Engineer]
      active: true
      signing_keys: ['ssh-ed25519 AAAA...']

ACCESS     Owner - exactly one; the only one who can hand over ownership; can do everything an Admin can.
           Admin - manages people, roles (and later workflows and overrides).
           Member - works on parts.
           Anyone who is not in the file, or whose entry is switched off, is READ-ONLY: they can look and
           open files, nothing else. A vault with no people file yet is in "legacy" mode: everybody may do
           everything (that is how a vault starts, until someone sets up the team).

WHO AM I   Litterbox never handles passwords: Git and the host sign you in. To learn which host account you are
           signed in as, it takes a lock on .litterbox/whoami, reads the owner name the host reports, and lets
           go again. That name is remembered in .git/litterbox-identity.json so Litterbox works offline, and is
           looked up again after a day (or when you press Who am I?). The person whose host_names include that
           name is you.

The checks here are process control: Git itself can't stop someone with push access from bypassing Litterbox.
The pre-push check, the audit on Get Latest and (optionally) the host's own CI are what catch that.
"""
