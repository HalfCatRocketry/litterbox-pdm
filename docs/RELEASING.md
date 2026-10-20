# Releasing Litterbox

How a new version gets from your computer to everyone's installed copy.

```
you change app/version.py + CHANGELOG.md, push, and push a tag like v0.1.1
        |
GitHub builds the program, tests that it starts, builds the installer, and signs the update information
        |
a GitHub Release appears with: Litterbox-Setup-0.1.1.exe, latest.json, latest.json.sig
        |
installed copies see it next time they start, ask "Update now?", and update themselves
```

## One-time setup

You need a GitHub account and Git on your computer. You do not need Python tools for building: GitHub builds on its
own Windows machine. (You need Python only to make the signing key in step 3.)

### 1. Create the repository
On GitHub: **New repository**, name `litterbox-pdm`, **Public**. Choose a license when you create it (open source
needs one; MIT is a common simple choice). Updates are fetched from this repository's public Releases, so it must be public.

### 2. Put the files in
Clone it to `C:\Litterbox\litterbox-pdm`, then arrange the files like this:

```
litterbox-pdm/
  .github/workflows/release.yml
  app/                       <- everything from C:\Litterbox\app\ goes here (the .py files, assets\, tests\)
    assets/ ...
    tests/ ...
    litterbox_gui.py ... version.py updater.py build_info.py selftest.py ...
  packaging/                 <- litterbox.spec  installer.iss  keygen.py  write_build_info.py
                                make_manifest.py  check_version.py
  docs/RELEASING.md
  CHANGELOG.md
  README.md
  requirements.txt
  .gitignore
```

Don't copy `sw_rename_test.py` if you don't want it in the project; nothing needs it. From now on, run and edit
Litterbox from `C:\Litterbox\litterbox-pdm\app\` and put new files from Claude there.

### 3. Make the signing key (once)
```
pip install cryptography
python packaging\keygen.py
```
It prints a PRIVATE and a PUBLIC key. **Save the private one somewhere safe** (a password manager). Anyone with it can
sign updates that installed copies will trust, and if you lose it you can no longer update installed copies
automatically (people would have to reinstall by hand).

### 4. Give GitHub the private key
Repository **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**.
Name: `LITTERBOX_SIGNING_KEY`. Value: the PRIVATE key line. (The public key is worked out from it and built into the
program by the pipeline. You don't paste it anywhere.)

Also check **Settings** -> **Actions** -> **General** -> **Workflow permissions** allows GitHub Actions to create
releases (the workflow asks for `contents: write`; this matters only if your organization restricts it).

### 5. Commit and push
```
git add .
git commit -m "Add Litterbox 0.1.0"
git push
```

### 6. Try a test build first
On GitHub: **Actions** -> **Release** -> **Run workflow**. It builds everything but publishes nothing. When it
finishes, open the run and download the **Litterbox-Setup-0.1.0** artifact. If a step fails, open it to read why
and tell Claude the error text.

## Publishing a release

1. Edit `app/version.py`: set `VERSION = "0.1.1"`.
2. Add a `## 0.1.1` section at the top of `CHANGELOG.md`. Those lines become the notes people see.
3. Commit and push.
4. Tag and push the tag (the tag must be `v` + the version, or the pipeline stops):
   ```
   git tag v0.1.1
   git push origin v0.1.1
   ```
5. Wait for **Actions** to turn green (a few minutes). The release appears on the repository's **Releases** page.

Installed copies find it the next time they start (or when someone clicks "check for updates").

## Installing for someone else (for example a teammate)

1. They install Git for Windows (includes Git LFS).
2. They download `Litterbox-Setup-X.Y.Z.exe` from your latest release and run it. SmartScreen: **More info** -> **Run anyway**.
3. They need access to the vault on your host (for Azure DevOps, add them to the project) and they clone it into
   `C:\Litterbox\<vault name>`. The first git command opens the host's sign-in.
4. They start Litterbox. If `C:\Litterbox\settings.yaml` doesn't point at the vault yet, use **Add org...** in the app.
5. Add them in **Team...** (Owner or Admin). Their host name is shown by **Who am I?** on their computer.

## Things to know

- **A build that can't start is never published.** The pipeline starts the built program in a no-window self-test; if
  anything is missing from the build, it stops before publishing.
- **Updates change only the program.** Settings, logs and the vault in `C:\Litterbox` are never touched, and
  uninstalling doesn't remove them either.
- **A vault can require a newer Litterbox.** See `format_version` and `min_litterbox_version` in
  `app/version.py`'s description. Anyone behind is told to update.
- **Rolling back:** publish a newer version number with the fix. Installed copies only move forward.
- **The spare key.** Since 0.4.2 every build also trusts a spare public key (`SPARE_PUBLIC_KEYS` in
  `app/litterbox/user/updater.py`). Its private key is kept offline, never in GitHub.
- **If the signing key is lost or leaks:** put the spare's PRIVATE key in the `LITTERBOX_SIGNING_KEY` secret and
  publish a release. Copies from 0.4.2 on accept it. Copies older than 0.4.2 know only the old key and must be
  reinstalled by hand once. Then make a new spare with `keygen.py` and add its public key in place of the one now in use.
