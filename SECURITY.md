# Security policy

## Supported versions

Only the newest release is supported. Installed copies offer each new release when they start, so fixes reach
people by updating; older versions don't get fixes of their own.

## Reporting a vulnerability

Please report it privately, not in a public issue:

- **On GitHub:** the repository's **Security** tab, **Report a vulnerability**
  ([direct link](https://github.com/HalfCatRocketry/litterbox-pdm/security/advisories/new)).
- **By email**, if you'd rather: contact+litterbox@halfcatrocketry.com, with "Security" in the subject.

Say what you found, how to make it happen, and which version you used. Litterbox has one maintainer, so replies are
best-effort; expect an answer within a week or two. Once a fix is released, the report can be published as a
GitHub security advisory, crediting you if you like.

## What counts

- **Updates.** Installed copies trust only releases signed with Litterbox's update keys (`app/litterbox/user/updater.py`,
  `docs/RELEASING.md`). A way to make a copy install something not signed with those keys, to accept a withdrawn key,
  or to follow a "moved to" notice that wasn't signed by a spare key, is a vulnerability.
- **The installer and the release pipeline** (`packaging/`, `.github/workflows/`).
- **Problem reports.** Help > Report a problem takes passwords and tokens out of what it collects; something it should
  have taken out and didn't is a vulnerability.
- **Reading a vault.** A vault's files (records, settings, the team list) are written by everyone on the team. A file
  in a vault that makes Litterbox run a program, write outside the vault and `C:\Litterbox`, or crash in a way that
  loses work, is a vulnerability.

## What doesn't (by design)

- **Litterbox's permissions are not a security boundary.** Roles, Admins, restricted and hidden projects, and the checks
  before an upload all run in Litterbox on each person's own computer. They keep honest people from mistakes. Anyone
  who can push to a vault's repository can change it without Litterbox; **the Git host's access settings are what
  protect a vault.** Give write access only to people you trust with every part in it, and see the user guide's
  Projects section for what Restrict and Hide do and don't protect.
- Someone with access to your computer or your Windows account.
- SolidWorks, Git, Git LFS or the Git host themselves (report those to their makers).
