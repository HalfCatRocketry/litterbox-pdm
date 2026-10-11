"""Make the signing keys for updates. Run ONCE, on your own computer:

    python packaging/keygen.py

It prints a PRIVATE key and a PUBLIC key.
  * The PRIVATE key goes into the GitHub repository's secrets as LITTERBOX_SIGNING_KEY (docs/RELEASING.md says
    where). Keep a copy somewhere safe, such as a password manager. Never put it in the repository or send it
    to anyone. If it is lost, installed copies can no longer be updated automatically.
  * The PUBLIC key is built into the program by the release pipeline (derived from the private key), so you
    don't need to copy it anywhere. It is printed so you can see it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import updater  # noqa: E402

if __name__ == "__main__":
    private, public = updater.generate_keypair()
    print("PRIVATE key (secret - goes in the GitHub secret LITTERBOX_SIGNING_KEY):")
    print(private)
    print()
    print("PUBLIC key (not secret - built into the program for you):")
    print(public)
