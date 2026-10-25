# Releasing Litterbox

How a new version gets from the repository to everyone's installed copy, and what to do when something goes wrong.

```
change VERSION and CHANGELOG.md, commit, push, then push a tag like v0.6.5 (or v0.7.0-beta.1 for a beta)
        |
GitHub runs every test on Linux (a failure stops here: nothing is built)
        |
build (Windows, no secrets): the tests again, Litterbox.exe, its self-test, the installer
        |
publish (Linux, the "release" environment): signs the update information and publishes the release:
Litterbox-Setup-0.6.5.exe, latest.json, latest.json.sig (and notices.json, notices.json.sig if there are notices)
        |
installed copies see it at start-up (or Help > Check for updates), ask "Update now?", and update themselves
```

## Where things are

| What | Where |
|---|---|
| The version number | `app/litterbox/version.py`: `VERSION = "0.6.5"` |
| What changed, which becomes the release notes | `CHANGELOG.md`: one `## 0.6.5` section per version, newest first |
| The pipeline | `.github/workflows/release.yml` (on a tag; it runs `tests.yml` first) and `.github/workflows/tests.yml` (on every push to a branch) |
| The build recipe | `packaging/litterbox.spec` (PyInstaller; it starts from `app/main.py` and finds every module itself, and writes the `licenses` folder with `third_party_licenses.py`) |
| The installer | `packaging/installer.iss` (Inno Setup; installs for the current user, no administrator needed) |
| Pipeline helpers | `packaging/check_version.py`, `write_build_info.py`, `make_manifest.py` |
| The packages the pipeline installs, pinned with hashes | `packaging/requirements-build.txt` (from `requirements.txt`), `packaging/requirements-sign.txt` (from `requirements-sign.in`) |
| Making signing keys | `packaging/keygen.py` |
| Withdrawing a key, or saying the repository moved | `packaging/sign_notice.py`, which writes `packaging/notices.json` and its signature |
| How updates are checked and trusted | `app/litterbox/user/updater.py`, `update_notices.py` |
| The build self-test | `app/litterbox/user/selftest.py` (`python app/main.py --self-test`) |

## Publishing a release

1. **Check it first.** From `app/`: `python -m unittest discover -s tests -t .` (Windows skips the git tests), and
   the full suite, git tests too, from Git Bash: `python tools/run_tests.py --git` (or let GitHub's run on the push do it).
   Then `python app/main.py --self-test` should print `ok`. Try anything new in the running program with a real
   vault: the tests check the logic and the wiring, not the look.
2. **Set the version** in `app/litterbox/version.py`.
3. **Write the changelog section** `## 0.6.5` at the top of `CHANGELOG.md`, in plain words about what people see
   and do. That section, exactly, becomes the release notes.
4. **Commit and push** to `main`. `tests.yml` runs the tests on GitHub.
5. **Tag and push the tag.** The tag must be `v` followed by the version, or the pipeline stops:
   ```
   git tag v0.6.5
   git push origin v0.6.5
   ```
6. **Watch the run** in the repository's **Actions** tab (a few minutes). When it's green, the release is on the
   **Releases** page.

If a vault must not be opened by older copies after this release (a new record field they would misread, a new
setting they would ignore), raise `min_litterbox_version` for it: some features do this themselves when first used
(projects, the SolidWorks version setting). Changing the vault's file layout means raising `VAULT_FORMAT` in
`version.py`, which needs a migration plan.

## Betas

A beta is the next version before it's finished, for people who chose **Help > Get beta versions**. Nobody else is
offered it.

1. Set `VERSION` to the beta's version: the version it leads to, then `-beta.` and a number: `0.7.0-beta.1`,
   `0.7.0-beta.2`, ... (Nothing else is accepted: no `-rc`, no `-beta` without a number.)
2. Write a `## 0.7.0-beta.1` section in `CHANGELOG.md` (it becomes that beta's notes).
3. Commit, push, tag `v0.7.0-beta.1` and push the tag, as for a release.

The pipeline publishes it as a GitHub **pre-release**, so GitHub's "latest" release (what everyone else's copy reads)
stays the newest real release. It also puts the beta's `latest.json` on a pre-release called **beta-channel** (made
the first time), which is where beta copies look. A beta copy is offered the newer of the newest release and the
newest beta, so when `0.7.0` comes out, everyone on `0.7.0-beta.N` is offered it.

- A beta counts as the version it leads to for a vault's minimum: `0.7.0-beta.2` opens a vault that needs `0.7.0`,
  and a beta never writes its `-beta` number into a vault. So betas belong in a test vault, or with the whole team
  moving to the beta together.
- Leaving the beta channel keeps the beta until a newer release comes out: copies never go back a version.
- To finish: set `VERSION = "0.7.0"`, write `## 0.7.0` (covering everything since the last release, not just the last
  beta), and release it as usual.

## When the run fails

- **A test failed:** the release job stops before building, so nothing was published. Fix it, commit, push, then
  move the tag to the new commit and push it again:
  ```
  git tag -d v0.6.5
  git push origin :refs/tags/v0.6.5
  git tag v0.6.5
  git push origin v0.6.5
  ```
  Only do this while no release exists for the tag. Once a release is published, never move its tag: publish the
  next version instead.
- **"The tag is ... but version.py says ...":** the tag and `VERSION` differ. Fix one, then re-tag as above.
- **The built program failed its self-test:** something didn't make it into the build (often a module imported in
  an unusual way, or a data file). The step's log names it. Run `python app/main.py --self-test` locally too.
- **"No licence file was found for ...":** a package the program carries has no licence file `third_party_licenses.py`
  could find. Look at the package's files and, if its licence is somewhere unusual, teach `licence_files` where.
- **"THESE PACKAGES DO NOT MATCH THE HASHES":** a pinned package on PyPI isn't the file it was. Don't just update the
  hash: find out why (a re-upload by its maintainers is rare). If it's genuine, update the pins (below).
- **"The LITTERBOX_PUBLIC_KEY variable is missing", or "LITTERBOX_SIGNING_KEY doesn't belong to
  LITTERBOX_PUBLIC_KEY":** the variable or the secret is missing or from different key pairs (see the one-time setup
  below). The second one stops before anything is published: installed copies would have refused the release.
- **Signing failed, or "LITTERBOX_SIGNING_KEY is not a valid key":** the secret is missing or wrong, or isn't in the
  **release** environment.

**A test build** publishes nothing: **Actions > Release > Run workflow**. It builds everything and attaches the
installer to the run, to download from the run's page and try. It isn't signed (only tags reach the signing key),
which doesn't matter for trying it.

## The repository is private (on purpose, for now)

Installed copies look for updates at `https://github.com/<owner>/<repo>/releases/latest/download/latest.json`,
without signing in. GitHub answers that only for a public repository, so while the repository is private:

- **Installed copies don't update themselves.** The update check quietly finds nothing.
- **Releases are still built and published,** and anyone with access to the repository can download the installer
  from the Releases page while signed in to GitHub, and run it. It installs over the old version and keeps every
  setting.

When the repository is made public, every copy from the first signed release on starts updating itself, with no
change to the program.

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
key it trusts (and hasn't been told to stop trusting) and whose installer matches the fingerprint.

- **The release key.** Its private half is the `LITTERBOX_SIGNING_KEY` secret in the **release** environment, which
  only `v*` tags can use; only the publish job reads it. Its public half is the `LITTERBOX_PUBLIC_KEY` repository
  variable, which the build puts into the program (`write_build_info.py` writes `app/litterbox/build_info.py`), and
  which the publish job checks the secret against.
- **The spare key** (since 0.4.2). Its public half is in `SPARE_PUBLIC_KEYS` in `app/litterbox/user/updater.py`;
  its private half is kept offline by the owner, never in GitHub or the repository. The self-test checks every
  spare is a valid key. Only a spare can sign **notices** (below), so someone who stole the release key couldn't
  withdraw the spare or send installed copies somewhere else.
- **Revoked keys** (since 0.6.5). `REVOKED_PUBLIC_KEYS` in `updater.py` lists keys never to trust again, even as the
  key a copy was built with. Copies also keep the keys a notice withdrew (`revoked_update_keys` in their
  `settings.yaml`), so a withdrawal sticks even if the person never installs the update that came with it.
- **Notices** (since 0.6.5): `packaging/notices.json`, signed with a spare by `packaging/sign_notice.py` on your own
  computer, committed, and attached to every release by the pipeline. Copies read it with each update check. It can
  say which keys are withdrawn, and where releases have moved to.

### If the release key leaks or is lost

1. On your own computer, withdraw it with the spare:
   `python packaging/sign_notice.py --revoke <the release key's PUBLIC half>` (it asks for the spare's PRIVATE key).
2. Make the spare the release key: put the spare's PRIVATE key in the `LITTERBOX_SIGNING_KEY` secret (release
   environment), and its PUBLIC key in the `LITTERBOX_PUBLIC_KEY` variable.
3. Add the old release key to `REVOKED_PUBLIC_KEYS`, make a new spare with `keygen.py`, and put its public key in
   `SPARE_PUBLIC_KEYS` in place of the one now in use. Keep its private key offline.
4. Commit (with `notices.json` and its `.sig`) and publish a release. Copies from 0.4.2 on accept it (it is signed by
   a key they know as a spare); from 0.6.5 on, they also stop trusting the old key as soon as they check, whether or
   not they update. Older copies know only the old key and must be reinstalled by hand once.

### Moving or renaming the repository

Installed copies ask the address they were built with. Since 0.6.5 they follow a signed "moved to":

1. Make the new repository and set it up (the one-time setup below), and publish a release there first.
2. In the **old** repository: `python packaging/sign_notice.py --moved-to <new owner>/<new name>`, commit, and
   publish one last release (or upload the two files to its latest release:
   `gh release upload <tag> packaging/notices.json packaging/notices.json.sig --clobber`).
3. Keep the old repository (archived) for as long as anyone might still run an old copy. Copies older than 0.6.5
   never follow a move: their people must download the installer from the new place once.

In the new repository, take `moved_to` out of `notices.json` (or leave it: a copy never follows a move to where it
already looks).

## Updating the pinned packages

The pipeline installs only the exact files listed, with their hashes. To move to newer versions (say monthly, or
when Dependabot or a security alert says one has a fix), from the repository's top folder, with pip-tools
installed (`pip install pip-tools`) in a Python 3.12 on Windows:

```
pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url --upgrade --output-file packaging/requirements-build.txt requirements.txt
pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url --upgrade --output-file packaging/requirements-sign.txt packaging/requirements-sign.in
```

Run the tests with the new versions (`pip install -r packaging/requirements-build.txt`), commit both files, and make
a test build. Leave out `--upgrade` to change only what a changed `requirements.txt` asks for. Inno Setup is pinned
in `release.yml` (`choco install innosetup --version ...`); change it there.

## One-time setup (for a new repository)

For a fork, or if the repository ever has to be set up again:

1. **The signing key.** On your own computer: `pip install -r requirements.txt`, then
   `python packaging/keygen.py`. It prints a PRIVATE and a PUBLIC key. Keep the private one somewhere safe (a
   password manager): anyone with it can sign updates installed copies will trust, and without it they can't be
   updated automatically. Run it a second time for a spare, and put that public key in `SPARE_PUBLIC_KEYS`.
2. **The release environment.** Repository **Settings > Environments > New environment**, named `release`. Under
   **Deployment branches and tags**, choose **Selected branches and tags** and add the tag rule `v*`. Then **Add
   environment secret**: `LITTERBOX_SIGNING_KEY`, with the PRIVATE key line. (Not a repository secret: that any
   workflow on any branch could read.)
3. **The public key.** **Settings > Secrets and variables > Actions > Variables > New repository variable**, named
   `LITTERBOX_PUBLIC_KEY`, with the PUBLIC key line.
4. **Permissions.** **Settings > Actions > General > Workflow permissions** must let workflows create releases
   (the publish job asks for `contents: write`).
5. **Tags.** **Settings > Rules > Rulesets > New tag ruleset**: target `v*`, restrict creations, updates and
   deletions, with yourself on the bypass list, so nobody else can start a release.
6. **A test build** (**Actions > Release > Run workflow**) before the first tag.

## Things to know

- **A build that can't start is never published:** the pipeline runs the built `Litterbox.exe --self-test` and
  stops if it fails.
- **The Windows tests in the release job block a release too**, like the Linux ones (they were informational until
  they had passed in eight releases in a row, up to 0.5.5).
- **The build never sees the private key.** It installs other people's packages and runs every test; the signing
  happens in the publish job, which installs only the pinned `cryptography`.
- **Rolling back** means publishing a newer version with the fix. Installed copies only move forward.
- **Running from source:** `pip install -r requirements.txt`, then `python app/main.py`. A copy run from source
  never checks for updates (it has no `build_info.py` with a repository in it).
