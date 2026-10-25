"""Run on the maintainer's own computer, never in the pipeline: writes packaging/notices.json and its signature, signed
with a SPARE key (see app/litterbox/user/update_notices.py and docs/RELEASING.md). Commit both files; every release
after that carries them.

    python packaging/sign_notice.py --revoke <public key>          withdraw a key (repeat for several)
    python packaging/sign_notice.py --moved-to owner/name          say where releases have moved
    python packaging/sign_notice.py --show                         print what the current notices say

Keys already withdrawn stay withdrawn. The spare's PRIVATE key is asked for (it isn't shown or saved); it must be one
of SPARE_PUBLIC_KEYS in app/litterbox/user/updater.py, or installed copies would ignore the notices.
"""

import argparse
import getpass
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
from litterbox.user import update_notices  # noqa: E402
from litterbox.user import updater  # noqa: E402

NOTICES = HERE / update_notices.NOTICES_NAME
SIGNATURE = HERE / update_notices.NOTICES_SIGNATURE_NAME


def current(folder=HERE):
    """The notices in `folder` as they are (signed by a spare key), or none."""
    path, sig = Path(folder) / update_notices.NOTICES_NAME, Path(folder) / update_notices.NOTICES_SIGNATURE_NAME
    if not path.is_file() or not sig.is_file():
        return update_notices.NONE
    return update_notices.parse(path.read_bytes(), sig.read_text(encoding="ascii"), updater.SPARE_PUBLIC_KEYS,
                                updater.REVOKED_PUBLIC_KEYS, updater.signature_is_good)


def write(private_key, revoke=(), moved_to=None, folder=HERE):
    """Sign and write the notices (the current ones plus these). Returns the Notices written. Raises SystemExit
    with what's wrong."""
    try:
        public = updater.public_from_private(private_key)
    except Exception:
        raise SystemExit("That isn't a private key (the PRIVATE line keygen.py printed).") from None
    if public not in updater.SPARE_PUBLIC_KEYS:
        raise SystemExit("That key isn't one of SPARE_PUBLIC_KEYS in app/litterbox/user/updater.py: installed copies "
                         "would ignore what it signs.")
    if public in revoke:
        raise SystemExit("A key can't withdraw itself: sign with another spare.")
    for key in revoke:
        if not updater.is_public_key(key):
            raise SystemExit(f"'{key}' isn't a public key.")
    before = current(folder)
    try:
        raw = update_notices.build(before.revoked + tuple(revoke), before.moved_to if moved_to is None else moved_to)
    except update_notices.NoticeError as e:
        raise SystemExit(str(e)) from None
    signature = updater.sign(raw, private_key)
    found = update_notices.parse(raw, signature, updater.SPARE_PUBLIC_KEYS, updater.REVOKED_PUBLIC_KEYS,
                                 updater.signature_is_good)                  # read back as an installed copy would
    (Path(folder) / update_notices.NOTICES_NAME).write_bytes(raw)
    (Path(folder) / update_notices.NOTICES_SIGNATURE_NAME).write_text(signature, encoding="ascii")
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--revoke", action="append", default=[], metavar="PUBLIC_KEY")
    parser.add_argument("--moved-to", metavar="OWNER/NAME")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)
    if args.show or not (args.revoke or args.moved_to):
        notices = current()
        print(f"Withdrawn keys: {', '.join(notices.revoked) or 'none'}\nMoved to: {notices.moved_to or 'not moved'}")
        return 0
    found = write(getpass.getpass("Spare PRIVATE key (not shown): ").strip(), args.revoke, args.moved_to)
    print(f"Wrote {NOTICES.name} and {SIGNATURE.name}: {len(found.revoked)} key(s) withdrawn, "
          f"moved to {found.moved_to or 'nowhere'}. Commit both; the next release carries them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
