# Changelog

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