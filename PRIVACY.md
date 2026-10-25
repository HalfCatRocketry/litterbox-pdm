# Privacy policy

Litterbox is made by Half Cat Rocketry. This page says what information Litterbox sends anywhere, and what happens
to the problem reports people choose to send us. Questions or requests: contact+litterbox@halfcatrocketry.com.

## In short

- Litterbox has **no server and collects nothing on its own**: no accounts, no tracking, no usage statistics.
- It talks to **GitHub** to check for updates, and to **your team's Git host** to share your vault.
- A **problem report** reaches us only if you send it yourself, from your own email, after seeing what is in it.

## What Litterbox sends, and to whom

**Update checks (to GitHub).** When it starts, and when you choose Help > Check for updates, an installed Litterbox
downloads small files from this project's releases on GitHub (which version is newest, and signed notices about update
keys). The request carries nothing about you or your vault beyond what any download does: GitHub sees your computer's
internet address and that the request came from "Litterbox" and its version. Downloading an update works the same way.
GitHub's own [privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement)
covers what it does with that. To stop the check, add `update_check: false` to `C:\Litterbox\settings.yaml`.

**Your vault (to your team's Git host).** Your parts, files and records go only to the Git repository your team
chose (GitHub, Azure DevOps, GitLab or another host), through Git on your computer, and only when you or Litterbox
uploads or downloads. That host and your team decide who sees them; Half Cat Rocketry never receives them. The host's
own privacy policy covers what it keeps.

**Nothing else.** Litterbox keeps your settings and logs in `C:\Litterbox` on your own computer and sends them nowhere,
except in a problem report you send.

## Problem reports

Help > **Report a problem...** makes a report on your computer and lists exactly what goes in it before it is made:

- your comment, and the versions of Litterbox, Windows, Python, SolidWorks, Git and Git LFS;
- the problems in Litterbox's status bar and any unexpected errors from this session;
- Litterbox's log (unless you untick it): the git commands it ran, with part numbers, file names and check-in
  comments, and messages that can name people on your team or your vault's address;
- your Litterbox settings and your vault's shared settings (unless you untick them), which can show your Windows
  user name.

Passwords and tokens are taken out, and no CAD files, documents, part records or team list ever go in. Litterbox then
opens an email to contact+litterbug@halfcatrocketry.com with the report, **in your own email program**: nothing is
sent until you press Send, and you can open the report first. Your email address and name come with it, as with any
email.

**What we do with a report:** read it to find and fix the problem, and reply to you about it. We don't sell it, share
it, or use it for anything else. Only the people working on Litterbox see it. We keep a report only as long as we need
it to fix the problem and answer you, then delete it. Copies of the report stay on your computer in
`C:\Litterbox\logs\reports` (the newest five), where you can delete them.

**Your choices:** you can ask us to delete a report you sent, or to tell you what we kept from it, by writing to
contact+litterbox@halfcatrocketry.com. If you'd rather not send a report at all, describe the problem in a GitHub issue
instead, leaving out anything you don't want public.

## Changes

If this policy changes, the new version is published here, in the repository, with its history.
