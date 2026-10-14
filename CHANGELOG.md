# Changelog

## 0.4.0

- The command line is now one command, run from the `app` folder: `python -m litterbox <command>`, with the commands `status` (and the part actions: latest, checkout, checkin, save, undo, release, makecots, reopen, void), `new-part`, `scan`, `import` and `init-vault`. Their options are the same as before; `python -m litterbox <command> --help` lists them. The old `python litterbox_engine.py ...`, `python create.py ...`, `python scan.py ...`, `python importer.py ...` and `python init_vault.py ...` no longer work. To start the program from source, run `python app/main.py`.

## 0.3.2

- Litterbox now works in the background. Actions no longer lock up the window: click an action, it joins a queue and runs in order, and you can keep browsing, ticking parts and queueing more. Opening the Import window and switching org still wait for the queue to finish.
- New status banner at the top of the window: green "Ready", yellow "Working" (what is running and how many jobs are waiting), red "Error". An error stays red until you dismiss it; Details... shows what went wrong and what to do about it. Real problems no longer interrupt you with a pop-up.
- Parts with a job queued or running show "checking in 3 parts..." in the Status column and can't have anything else done to them until it finishes. Check In and Save Progress ask you not to save those parts in SolidWorks until the banner says Ready, and Open warns if the part is still being uploaded.
- Closing Litterbox while it is still working asks first.
- Check In now notices a part that was saved in SolidWorks after you pressed it, or while Litterbox was reading it. That part is not uploaded; it stays checked out to you, and the message tells you to Check In again when you have finished saving. The other parts carry on. (Litterbox does this by comparing each file's size and modified time, which costs next to nothing; it does not change any file's read-only state. Save Progress only checks for a save during the upload itself, since you are meant to keep working after it.)
- Fixed: Add org... opened the Org setup form (code, start number, digits), which made no sense for a vault that already exists. It now asks for just the repository's URL (the https address from your Git host's Clone button), clones it into `C:\Litterbox\<repository name>` in the background, reads the org code and numbering from the vault itself, and opens it. If the URL is already added, or the clone turns out not to be a vault yet, it says so plainly (and points to Create new vault...). Org setup... is still where you edit an org.
- Create new vault... now suggests 6 digits in the part number (was 5). Vaults that don't say how many digits they use keep 5, so no existing vault changes.
- **Part numbers now loop.** Numbers count up from the vault's start number to the highest the digits allow (999999 for 6 digits), then start again at 1 and go up to just below the start number, so the start number is only the first point of a complete loop and every number gets used. Zero is never used. Voided parts keep their numbers.
- When every part number is taken, New Part, the suggested number and Import say so plainly ("this vault has no part numbers left") instead of complaining about the number of digits.
- **Import numbering counts from the lowest free part number.** It still proposes numbers about 100 ahead (plus a random extra, so two big imports started together are unlikely to collide), but the 100 is now counted from the lowest free part number, not from the highest one in use, so one number typed in far above the rest no longer pushes imports up with it. Past the highest number the digits allow, it loops round to 1. If someone takes a proposed number while you work, the numbers Litterbox chose are swapped for the next free ones when you finish, as before.
- Create new vault no longer warns about a high start number leaving little room, since the numbers loop round.

## 0.3.1

- **Actions on many parts are much faster.** Check Out, Check In, Save Progress, Undo Checkout, Release, Unrelease, Void and Make COTS, and every step of a workflow (asking, signing, finishing, withdrawing), now download once and upload once for the whole selection instead of once per part, and take and release locks several at a time. Each part still gets its own history entry. Changes to part records (workflow steps, Release, Unrelease, Void, Make COTS) go in one commit per batch, with a line for each part in its message; Check In and Save Progress still make one commit per part. If one part can't be done (somebody has it checked out, say) it is reported and the rest carry on; if the upload itself fails, nothing is left half done. Updating references on several assemblies, and Update references, work the same way.
- Parts you void are unselected automatically (they are hidden by default, so a leftover tick was invisible).
- Release, Unrelease, Void and Make COTS now work on several selected parts at once even in a vault with no workflow; before, they needed one part at a time.
- **Reopen is now called Unrelease** everywhere it is shown (the button, pop-ups, Team > Workflows and a part's history). Records and settings keep their old internal name, so nothing in an existing vault changes.
- **Buttons grey out** when they can't be used on what is selected: a button lights up only if every selected part suits it (for example Check Out is grey if any selected part is already checked out).
- Parts list: new **Deselect All** button.
- Import: "Import all as the same base number" box. Leave the number empty for the next free one, or type your own; if it is already in use the new variants start at the lowest free number. Litterbox refuses, and says so, if the parts won't fit in the variant numbers that are left.
- Import review: **Select All** and **Deselect All** buttons.
- Shift-click selects everything between the last click and this one in every list with boxes (Import, References).
- New vault setting commit_style: Check In and Save Progress on several parts make one commit per part (the default) or, if an Admin chooses it, one commit for the whole batch, which is faster (each commit takes about a second). Admins and the Owner change it in Team > Vault Settings...; it applies to everyone. The same dialog also edits release_rule (warn / block / off) and require_signatures, which were hand-edited in .litterbox/config.yaml before (turning signatures on asks first).
- Debug mode now logs where a batch's time went, e.g. `Timing: check in on 20 part(s) took 31.2s. git commit x20 = 19.8s; git push x1 = 6.1s; ...`.
- Very large batches (over 100 parts) now still make a single commit when one is asked for.

## 0.3.0

- Workflows are rebuilt. Pressing Release (or Reopen, Void, Make COTS) in a vault that has workflows for that action opens a Workflow window: pick a template (T1, T2... or your own), choose a person for each sign-off, add optional extra sign-offs, and submit. Several parts can go through one workflow together; the people sign once for the whole batch.
- Team > Workflows has a tab for each action. A template is a list of sign-offs; list a role twice for two sign-offs, and use "+ or" to let someone with any of several roles fill a sign-off (for example Manager or Chief). Each template says whether one person may fill more than one sign-off and whether the person who asks may sign. "Add standard workflows" adds Release T1, T2 and T3 and one workflow for each other action.
- The people who sign are named when the workflow starts; My Tasks shows each person what is waiting on them. The person who asked (or an Admin) can change who signs, withdraw the request, or finish it; an Admin can still override with a recorded reason.
- Release, Reopen and Void happen as soon as the last person signs. Make COTS waits for the button to be pressed again. Revise and Cancel Revision don't have workflows yet.
- Delete .litterbox/workflows.yaml before updating a vault that used 0.2.0 workflows, and set them up again in Team > Workflows. A vault with workflows asks everyone to update to 0.3.0.
- Check Out, Check In, Save Progress, Undo Checkout, Release, Reopen, Void and Make COTS act on the parts whose boxes are selected. Clicking a row highlights it in blue, which Open, Open Drawing, References and History use.
- Parts-list tick boxes now read "selected" throughout the program.

## 0.2.0

- **Release workflow.** An Admin can require sign-offs before a part is released (Team... > Workflows...). Pressing
  Release then asks the people holding the required roles; the part is released when everyone needed has signed.
- **My Tasks** lists the sign-offs waiting on you. Reject (with a reason), withdraw, and Admin override (with a
  recorded reason) are all there.
- Vaults that use a workflow ask everyone to update to 0.2.0 first.
- Team changes are saved together. The Person, Roles and Workflows windows have an OK button that keeps your change in a draft; the Team window's Save uploads everything at once. Cancel or Close with unsaved changes asks "Discard changes?" (Discard / Keep editing). Discarding in a sub-window drops only that window's changes.
- Tick boxes down the left of the part list pick several parts at once for Check Out, Check In, Save Progress and Undo Checkout.
- Saving when nothing changed now shows an information message instead of an error.
- Pop-ups opened from the Team window stay on top of it (for example Who am I?).

## 0.1.1

- **Create new vault...** in the org menu (and `init_vault.py` on the command line) turns an empty cloned
  repository into a vault: LFS and lock settings, ignore rules, the vault's settings, and the first Owner.
- Fixed buttons that only responded when clicked in the middle.
- A clearer message when the update check gets a 404 (usually a private repository).

## 0.1.0

First installable release.

- Check parts out and in with Git LFS locks, and release them.
- Revisions, references and where-used, and a stale-reference check.
- Team list with roles and optional signed commits.
- Installer, and an update check when Litterbox starts.
