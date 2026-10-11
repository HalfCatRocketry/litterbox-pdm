"""Used by the release pipeline: writes app/build_info.py so the built program knows which GitHub repository
to ask for updates and which public key to trust.

    python packaging/write_build_info.py --repo owner/litterbox-pdm      (the private key comes from the
                                                                          LITTERBOX_SIGNING_KEY environment variable)
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import updater  # noqa: E402

TEMPLATE = '''"""Written by the release pipeline (packaging/write_build_info.py). Do not edit."""

REPO = "{repo}"
PUBLIC_KEY = "{key}"
'''


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "app" / "build_info.py"))
    args = parser.parse_args(argv)
    private = os.environ.get("LITTERBOX_SIGNING_KEY", "").strip()
    if not private:
        print("The LITTERBOX_SIGNING_KEY secret is missing. See docs/RELEASING.md, one-time setup.")
        return 1
    if not updater.REPO_NAME.match(args.repo):
        print(f"'{args.repo}' is not an owner/name repository.")
        return 1
    try:
        public = updater.public_from_private(private)
    except Exception:
        print("LITTERBOX_SIGNING_KEY is not a valid key. Run packaging/keygen.py and paste the PRIVATE line.")
        return 1
    Path(args.out).write_text(TEMPLATE.format(repo=args.repo, key=public), encoding="utf-8")
    print(f"Wrote {args.out} for {args.repo}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
