"""
scan.py - the import scan on the command line: python -m litterbox.cli.scan --help
"""

import argparse
import sys
from pathlib import Path

from litterbox.importing import manifest as mf
from litterbox.importing import scan


def main(argv=None, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description="Litterbox: scan old CAD folders and write an import manifest (read-only)")
    parser.add_argument("folders", nargs="+", help="the folders to scan")
    parser.add_argument("--out", default="import-manifest.yaml", help="where to write the manifest")
    parser.add_argument("--repo", help="your vault folder: files already imported from the same path are left out")
    parser.add_argument("--no-hash", action="store_true", help="skip hashing (much faster, but no exact-copy report)")
    parser.add_argument("--force", action="store_true", help="overwrite the manifest file if it already exists")
    args = parser.parse_args(argv)

    out = Path(args.out).resolve()
    try:
        for folder in args.folders:
            if scan._inside(out, str(Path(folder).resolve())):         # resolved the same way as `out` (Windows short names)
                raise scan.ScanError(f"The manifest can't be written inside a folder being scanned ({folder}). "
                                "Choose another place with --out.")
        if out.exists() and not args.force:
            raise scan.ScanError(f"{out} already exists. It may hold edits you made. Use --force to replace it, "
                            "or choose another name with --out.")

        def show(done, total, path):
            if done == total or done % 50 == 0:
                print(f"\r  hashed {done:,} of {total:,} files", end="", flush=True)

        result = scan.scan(args.folders, repo=args.repo, hash_files=not args.no_hash, progress=show)
        print()
        mf.save(result, out)
    except (scan.ScanError, mf.ManifestError) as e:
        print(f"\nERROR: {e}")
        return 1
    print(scan.format_report(result))
    print(f"\nManifest written to {out}\nNothing in your CAD folders was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
