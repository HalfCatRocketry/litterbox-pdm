# Litterbox PDM

A lightweight product data manager (PDM) for small teams using SolidWorks. It uses Git and Git LFS locking to check CAD parts in and out, track revisions and references, and release parts, with a simple Windows app on top. How to use it: `docs/Litterbox_User_Guide.docx`.

## Install (Windows)

1. Install [Git for Windows](https://git-scm.com/download/win). It includes Git LFS.
2. Download `Litterbox-Setup-X.Y.Z.exe` from the [latest release](../../releases/latest) and run it.
   Windows SmartScreen may say the app is unrecognized: choose **More info**, then **Run anyway**.
   It installs for your user only and needs no administrator rights.
3. Clone your team's vault (the shared Git repository of parts) into `C:\Litterbox\<vault name>`, then start Litterbox.
   Your settings live in `C:\Litterbox\settings.yaml`.

Litterbox checks for a newer version when it starts and asks before updating. To turn that off, add
`update_check: false` to `C:\Litterbox\settings.yaml`.

## Run from source

```
pip install -r requirements.txt
python app/main.py
```

The command line (from the `app` folder): `python -m litterbox <command>`; run `python -m litterbox` to list the commands.

The title bar says "(from source)" for a source copy, which never updates itself.

## Folders

| Folder | What is in it |
|---|---|
| `app/` | The program: `main.py` starts it, `litterbox/` is the code (see `docs/ARCHITECTURE.md`), `tests/` the tests |
| `docs/` | The user guide (`Litterbox_User_Guide.docx`), how the code is laid out (`ARCHITECTURE.md`) and the roadmap (`REMINDERS.md`) |
| `tools/` | SolidWorks experiments and small developer scripts |
| `packaging/` | Builds the installer and signs updates (PyInstaller, Inno Setup, scripts) |
| `.github/workflows/` | The pipeline that builds and publishes a release when you push a version tag |