"""Used by the release pipeline: writes app/litterbox/build_info.py so the built program knows which GitHub repository
to ask for updates and which public key to trust.

    python packaging/write_build_info.py --repo owner/litterbox-pdm --public-key <key>

The public key is the repository variable LITTERBOX_PUBLIC_KEY: not secret, so the build never needs the private key
(only the signing job does, packaging/make_manifest.py, which checks the two belong together).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from litterbox.user import updater  # noqa: E402

TEMPLATE = '''"""Written by the release pipeline (packaging/write_build_info.py). Do not edit."""

REPO = "{repo}"
PUBLIC_KEY = "{key}"
'''


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--public-key", default="")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "app" / "litterbox" / "build_info.py"))
    args = parser.parse_args(argv)
    public = args.public_key.strip()
    if not public:
        print("The LITTERBOX_PUBLIC_KEY variable is missing. See docs/RELEASING.md, one-time setup.")
        return 1
    if not updater.REPO_NAME.match(args.repo):
        print(f"'{args.repo}' is not an owner/name repository.")
        return 1
    if not updater.is_public_key(public):
        print("LITTERBOX_PUBLIC_KEY is not a valid public key. It is the PUBLIC line keygen.py printed.")
        return 1
    Path(args.out).write_text(TEMPLATE.format(repo=args.repo, key=public), encoding="utf-8")
    print(f"Wrote {args.out} for {args.repo}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
