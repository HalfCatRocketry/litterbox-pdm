# Changelog

## 0.3.1
- Reopen is now called Unrelease everywhere it is shown (the button, pop-ups, Team > Workflows and a part's history). Records and settings keep their old internal name, so nothing in an existing vault changes.
- Buttons grey out when they can't be used on what is selected: a button lights up only if every selected part suits it (for example Check Out is grey if any selected part is already checked out).
- Parts list: new Deselect All button.
- Import: "Import all as the same base number" box. Leave the number empty for the next free one, or type your own; if it is already in use the new variants start at the lowest free number. Litterbox refuses, and says so, if the parts won't fit in the variant numbers that are left.
- Import review: Select All and Deselect All buttons.
- Shift-click selects everything between the last click and this one in every list with boxes (Import, References).

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