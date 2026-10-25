"""Used by the release pipeline: makes latest.json (what the update check reads), its signature, and the
release notes, next to a built installer.

    python packaging/make_manifest.py --version 0.1.0 --repo owner/litterbox-pdm \\
        --installer dist/installer/Litterbox-Setup-0.1.0.exe --out dist/release --public-key <key>

The private key comes from the LITTERBOX_SIGNING_KEY environment variable; it must belong to --public-key (the
LITTERBOX_PUBLIC_KEY variable the program was built with), or installed copies would refuse the release. The release
notes are the section for this version in CHANGELOG.md. With packaging/notices.json there (sign_notice.py), it and
its signature are copied out too, to go with the release.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
from litterbox.user import update_notices  # noqa: E402
from litterbox.user import updater  # noqa: E402
from litterbox import version  # noqa: E402


def notes_for(changelog, wanted):
    """The CHANGELOG section for this version ('## 0.1.0' or '## [0.1.0] - date'), without its heading."""
    lines, found, collected = changelog.splitlines(), False, []
    for line in lines:
        if line.startswith("## "):
            if found:
                break
            found = bool(re.match(rf"##\s*\[?v?{re.escape(wanted)}\]?(\s|$)", line))
            continue
        if found:
            collected.append(line)
    return "\n".join(collected).strip()


def build(version_text, repo, installer, out_dir, private_key, changelog="", notices_dir=None):
    installer = Path(installer)
    data = installer.read_bytes()
    manifest = {
        "schema": updater.MANIFEST_SCHEMA,
        "version": version_text,
        "notes": notes_for(changelog, version_text),
        "installer": {
            "name": installer.name,
            "url": f"https://github.com/{repo}/releases/download/v{version_text}/{installer.name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        },
    }
    raw = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / updater.MANIFEST_NAME).write_bytes(raw)
    (out / updater.SIGNATURE_NAME).write_text(updater.sign(raw, private_key), encoding="ascii")
    (out / "notes.md").write_text(manifest["notes"] or f"Litterbox {version_text}", encoding="utf-8")
    # Prove it works the way the program will use it, before anything is published.
    public = updater.public_from_private(private_key)
    updater.parse_manifest(raw, (out / updater.SIGNATURE_NAME).read_text(), public, repo)
    notices_dir = Path(notices_dir) if notices_dir else ROOT / "packaging"
    for name in (update_notices.NOTICES_NAME, update_notices.NOTICES_SIGNATURE_NAME):
        if (notices_dir / name).is_file():
            shutil.copyfile(notices_dir / name, out / name)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--installer", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--public-key", default="")
    args = parser.parse_args(argv)
    private = os.environ.get("LITTERBOX_SIGNING_KEY", "").strip()
    if not private:
        print("The LITTERBOX_SIGNING_KEY secret is missing. See docs/RELEASING.md, one-time setup.")
        return 1
    try:
        public = updater.public_from_private(private)
    except Exception:
        print("LITTERBOX_SIGNING_KEY is not a valid key. It is the PRIVATE line keygen.py printed.")
        return 1
    if args.public_key and args.public_key.strip() != public:
        print("LITTERBOX_SIGNING_KEY doesn't belong to LITTERBOX_PUBLIC_KEY, the key the program was built to trust. "
              "Installed copies would refuse this release. See docs/RELEASING.md, one-time setup.")
        return 1
    if args.version != version.VERSION:
        print(f"--version {args.version} does not match app/litterbox/version.py ({version.VERSION}).")
        return 1
    changelog_path = ROOT / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8") if changelog_path.is_file() else ""
    manifest = build(args.version, args.repo, args.installer, args.out, private, changelog)
    print(f"Wrote {updater.MANIFEST_NAME}, {updater.SIGNATURE_NAME} and notes.md for {manifest['version']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
