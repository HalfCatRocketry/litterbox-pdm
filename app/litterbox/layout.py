"""
layout.py - where everything lives inside a vault. One place for every fixed folder and file name.

    PN-logs/HCR-00042-001.yaml        the part records                    LOG_DIR_NAME
    cad/HCR-00042-001_A.SLDPRT        CAD files (Git LFS, lockable)       CAD_DIR_NAME
    cancelled-revs/CANCELLED_...      revisions cancelled before release  CANCELLED_DIR_NAME, CANCELLED_PREFIX
    .litterbox/config.yaml            shared vault settings               CONFIG_DIR, CONFIG_FILE
    .litterbox/people.yaml            the team                            PEOPLE_FILE
    .litterbox/workflows.yaml         sign-off templates                  WORKFLOWS_FILE
    .litterbox/allowed_signers        generated from people.yaml          ALLOWED_SIGNERS_FILE
    .litterbox/whoami                 a lock used to learn who you are    WHOAMI_FILE

Changing any of these changes the vault format (see version.VAULT_FORMAT).
"""

LOG_DIR_NAME = "PN-logs"
CAD_DIR_NAME = "cad"
CANCELLED_DIR_NAME = "cancelled-revs"       # revisions that were cancelled before release are kept here
CANCELLED_PREFIX = "CANCELLED_"

CONFIG_DIR = ".litterbox"
CONFIG_FILE = "config.yaml"                 # a file name inside CONFIG_DIR (the others below are paths)
PEOPLE_FILE = f"{CONFIG_DIR}/people.yaml"
WHOAMI_FILE = f"{CONFIG_DIR}/whoami"
ALLOWED_SIGNERS_FILE = f"{CONFIG_DIR}/allowed_signers"
WORKFLOWS_FILE = f"{CONFIG_DIR}/workflows.yaml"
