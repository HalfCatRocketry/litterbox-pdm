# Litterbox PDM

A lightweight product data manager (PDM) for small hardware teams that design in SolidWorks. It keeps the team's CAD
files in one shared vault, lets only one person edit a part at a time, numbers parts, tracks revisions and releases,
runs sign-off workflows and works out bills of materials, with a simple Windows program on top.

Litterbox has **no server**. A vault is an ordinary Git repository with Git LFS, on a Git host such as GitHub, Azure
DevOps or GitLab, and Litterbox turns Git's commits and file locks into check out, check in, release and revise.
Nobody on the team needs to know Git.

> **Litterbox is new.** It is used by one team so far, and some features have had little use outside it, so expect
> bugs. If something goes wrong, please use **Help > Report a problem...** in the program: it makes a report of what
> happened (you can look at it before sending) and opens an email with it.

## What it does

- **Check out and check in.** Checking out locks a part's files on the Git host, so only one person edits it at a
  time; everyone else's copy stays read-only.
- **Part numbers** in your org's format (for example `HCR-100010-001`), handed out without clashes.
- **Revisions and releases**, with sign-off workflows and change orders (ECOs) if the team wants them.
- **Bills of materials**, counted from SolidWorks assemblies, with purchased parts, kits and costs.
- **STEP and PDF files** made at release, for people who don't run SolidWorks.
- **Documents**, projects, Team and project folders, and a full history of who changed what, when and why.

## What you need

- **Windows** 10 or 11 (64-bit).
- **[Git for Windows](https://git-scm.com/download/win)**, which includes Git LFS.
- **A Git host that supports Git LFS file locking**: GitHub, Azure DevOps and GitLab do. Hosts limit LFS storage
  differently (GitHub's free allowance is small), and a vault's storage only grows, so check the limits first.
- **SolidWorks**, to model. Litterbox has been tried with SolidWorks 2024. Without it you can still look at parts,
  open PDFs, run workflows, and manage purchasing and documents.
- **The `C:\Litterbox` folder.** Every vault lives in `C:\Litterbox\<vault name>` on every computer, so the paths
  inside SolidWorks assemblies work for everyone.

## Install

1. Install Git for Windows.
2. Download `Litterbox-Setup-X.Y.Z.exe` from the [latest release](../../releases/latest) and run it.
   Windows SmartScreen may say the app is unrecognized: choose **More info**, then **Run anyway**.
   It installs for your user only and needs no administrator rights.
3. Start Litterbox, then:
   - **To start a new team:** create an empty repository (no README) on your Git host, then choose
     **File > Create new org...** and paste its address. You become the vault's Owner and add the team on the
     **Team** screen.
   - **To join a team:** ask its Owner or an Admin for access to the vault's repository, then choose
     **File > Add org...** and paste its address.

Litterbox checks for a newer version when it starts and asks before updating. Updates are signed, and the program
only installs one signed by the Litterbox maintainers. To turn the check off, add `update_check: false` to
`C:\Litterbox\settings.yaml`. Your settings, logs and vaults are all in `C:\Litterbox`; updating or uninstalling
never touches them. To try new versions early, choose **Help > Get beta versions** (expect more bugs).

**The [user guide](Litterbox_User_Guide.pdf)** (also as `docs/Litterbox_User_Guide.docx`) covers everything, including the decisions to make before
setting up a team (the org code and part number format can't be changed later).

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
| `docs/` | The user guide (`Litterbox_User_Guide.docx`), how the code is laid out (`ARCHITECTURE.md`) and how to release (`RELEASING.md`) |
| `tools/` | SolidWorks experiments and small developer scripts |
| `packaging/` | Builds the installer and signs updates (PyInstaller, Inno Setup, scripts) |
| `.github/workflows/` | The pipeline that builds and publishes a release when you push a version tag |

## Security

To report a security problem, please follow [SECURITY.md](SECURITY.md) rather than opening a public issue. Note that
Litterbox's roles and permissions run on each person's computer: the Git host's access settings are what protect a
vault.

## Licence

Litterbox is free software under the [MIT licence](LICENSE). The installed program carries the licences of the
other programs it is built with in its `licenses` folder (Python, customtkinter, PyYAML, cryptography, pywin32 and
others).
