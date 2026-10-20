# Releasing Litterbox

How a new version gets from the repository to everyone's installed copy, and what to do when something goes wrong.

```
change VERSION and CHANGELOG.md, commit, push, then push a tag like v0.4.4
        |
GitHub runs every test on Linux (a failure stops here: nothing is built)
        |
GitHub builds Litterbox.exe on Windows, checks it starts, builds the installer, and signs the update information
        |
a GitHub Release appears with: Litterbox-Setup-0.4.4.exe, latest.json, latest.json.sig
        |
installed copies see it at start-up (or Help > Check for updates), ask "Update now?", and update themselves
```

## Where things are

| What | Where |
|---|---|
| The version number | `app/litterbox/version.py`: `VERSION = "0.4.4"` |
| What changed, which becomes the release notes | `CHANGELOG.md`: one `## 0.4.4` section per version, newest first |
| The pipeline | `.github/workflows/release.yml` (on a tag) and `.github/workflows/tests.yml` (on every push) |
| The build recipe | `packaging/litterbox.spec` (PyInstaller; it starts from `app/main.py` and finds every module itself) |
| The installer | `packaging/installer.iss` (Inno Setup; installs for the current user, no administrator needed) |
| Pipeline helpers | `packaging/check_version.py`, `write_build_info.py`, `make_manifest.py` |
| Making signing keys | `packaging/keygen.py` |
| How updates are checked and trusted | `app/litterbox/user/updater.py` |
| The build self-test | `app/litterbox/user/selftest.py` (`python app/main.py --self-test`) |

## Publishing a release

1. **Check it first.** From `app/`: `python -m unittest discover -s tests -t .` (Windows skips the git tests), and
   the full suite on Linux or WSL: `wsl -d Ubuntu -u root -- bash /mnt/c/Litterbox/litterbox-pdm/refactor_plan/run_suite_wsl.sh`.
   Then `python app/main.py --self-test` should print `ok`. Try anything new in the running program with a real
   vault: the tests check the logic and the wiring, not the look.
2. **Set the version** in `app/litterbox/version.py`.
3. **Write the changelog section** `## 0.4.4` at the top of `CHANGELOG.md`, in plain words about what people see
   and do. That section, exactly, becomes the release notes.
4. **Commit and push** to `main`. `tests.yml` runs the tests on GitHub.
5. **Tag and push the tag.** The tag must be `v` followed by the version, or the pipeline stops:
   ```
   git tag v0.4.4
   git push origin v0.4.4
   ```
6. **Watch the run** in the repository's **Actions** tab (a few minutes). When it's green, the release is on the
   **Releases** page.

If a vault must not be opened by older copies after this release (a new record field they would misread, a new
setting they would ignore), raise `min_litterbox_version` for it: some features do this themselves when first used
(projects, the SolidWorks version setting). Changing the vault's file layout means raising `VAULT_FORMAT` in
`version.py`, which needs a migration plan.

## When the run fails

- **A test failed:** the release job stops before building, so nothing was published. Fix it, commit, push, then
  move the tag to the new commit and push it again:
  ```
  git tag -d v0.4.4
  git push origin :refs/tags/v0.4.4
  git tag v0.4.4
  git push origin v0.4.4
  ```
  Only do this while no release exists for the tag. Once a release is published, never move its tag: publish the
  next version instead.
- **"The tag is ... but version.py says ...":** the tag and `VERSION` differ. Fix one, then re-tag as above.
- **The built program failed its self-test:** something didn't make it into the build (often a module imported in
  an unusual way, or a data file). The step's log names it. Run `python app/main.py --self-test` locally too.
- **Signing failed, or "LITTERBOX_SIGNING_KEY is not a valid key":** the secret is missing or wrong (see the
  one-time setup below).

**A test build** publishes nothing: **Actions > Release > Run workflow**. It builds everything and attaches the
installer to the run, to download from the run's page and try.

## The repository is private (on purpose, for now)

Installed copies look for updates at `https://github.com/<owner>/<repo>/releases/latest/download/latest.json`,
without signing in. GitHub answers that only for a public repository, so while the repository is private:

- **Installed copies don't update themselves.** The update check quietly finds nothing.
- **Releases are still built and published,** and anyone with access to the repository can download the installer
  from the Releases page while signed in to GitHub, and run it. It installs over the old version and keeps every
  setting.

When the repository is made public, every copy from the first signed release on starts updating itself, with no
change to the program. If it is ever moved or renamed, installed copies keep asking the old address, so read
"Update trust" in `docs/REMINDERS.md` (a signed "moved to") before doing that.

## Installing for someone new

1. They install **Git for Windows** (it includes Git LFS).
2. They download `Litterbox-Setup-X.Y.Z.exe` from the latest release and run it. If SmartScreen warns: **More
   info > Run anyway** (the installer isn't code-signed).
3. They need access to the vault's repository on its Git host. In Litterbox: **File > Add org...** and paste the
   repository's address. The first download opens the host's sign-in.
4. An Owner or Admin adds them on the **Team** screen. Their host name is shown by **Who am I?** on their
   computer.

Everything Litterbox keeps for a person is in `C:\Litterbox`: `settings.yaml`, the logs and the vaults.
Uninstalling or updating never touches it.

## Keys and trust

Every release carries `latest.json` (the version, where the installer is, and its SHA-256 fingerprint) and
`latest.json.sig`, a signature on it. An installed copy only installs an update whose `latest.json` is signed by a
key it trusts and whose installer matches the fingerprint.

- **The release key.** Its private half is the `LITTERBOX_SIGNING_KEY` secret in GitHub. The pipeline works out
  the public half and builds it into the program (`write_build_info.py` writes `app/litterbox/build_info.py`).
- **The spare key** (since 0.4.2). Its public half is in `SPARE_PUBLIC_KEYS` in `app/litterbox/user/updater.py`;
  its private half is kept offline by the owner, never in GitHub or the repository. The self-test checks every
  spare is a valid key.
- **If the release key is lost or leaks:** put the spare's PRIVATE key in the `LITTERBOX_SIGNING_KEY` secret and
  publish a release. Copies from 0.4.2 on accept it; older copies know only the old key and must be reinstalled by
  hand once. Then make a new spare with `keygen.py` and put its public key in `SPARE_PUBLIC_KEYS` in place of the
  one now in use.
- Still to come: a list of revoked keys (`docs/REMINDERS.md`, "Update trust").

## One-time setup (already done for this repository)

For a fork, or if the repository ever has to be set up again:

1. **The signing key.** On your own computer: `pip install -r requirements.txt`, then
   `python packaging/keygen.py`. It prints a PRIVATE and a PUBLIC key. Keep the private one somewhere safe (a
   password manager): anyone with it can sign updates installed copies will trust, and without it they can't be
   updated automatically. Run it a second time for a spare, and put that public key in `SPARE_PUBLIC_KEYS`.
2. **The secret.** Repository **Settings > Secrets and variables > Actions > New repository secret**, named
   `LITTERBOX_SIGNING_KEY`, with the PRIVATE key line. Nothing else needs pasting: the public key is worked out
   from it.
3. **Permissions.** **Settings > Actions > General > Workflow permissions** must let workflows create releases
   (the release workflow asks for `contents: write`).
4. **A test build** (**Actions > Release > Run workflow**) before the first tag.

## Things to know

- **A build that can't start is never published:** the pipeline runs the built `Litterbox.exe --self-test` and
  stops if it fails.
- **The Windows tests in the release job are informational** (`continue-on-error` in `release.yml`); the Linux
  tests block. Once the Windows run is reliably green, remove that line so it blocks too.
- **Rolling back** means publishing a newer version with the fix. Installed copies only move forward.
- **Running from source:** `pip install -r requirements.txt`, then `python app/main.py`. A copy run from source
  never checks for updates (it has no `build_info.py` with a repository in it).
