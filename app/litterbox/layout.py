"""
layout.py - where everything lives inside a vault. One place for every fixed folder and file name.

    PN-logs/HCR-00042-001.yaml        the part records                    LOG_DIR_NAME
    cad/HCR-00042-001_A.SLDPRT        CAD files (Git LFS, lockable)       CAD_DIR_NAME
    cad/cancelled-revs/CANCELLED_...  revisions cancelled before release  CANCELLED_DIR_NAME, CANCELLED_PREFIX
                                      (cancelled-revs/ at the top of the vault before 0.6.3: LEGACY_CANCELLED_DIR_NAME;
                                      file rules version 4 moves it, vault/git_attributes.py)
    ECO/ECO-0001.yaml                 engineering change orders           ECO_DIR_NAME
    DOC-logs/PROP-0001.yaml           the document records                DOC_LOG_DIR_NAME
    documents/PROP-0001_A.docx        documents' files (Git LFS, lockable) DOC_DIR_NAME
    toolbox/browser/...               the team's SolidWorks Toolbox, when it has one (an Admin uploads it)
                                                                          TOOLBOX_DIR_NAME
    folders/<time>-<id>.yaml          Team and project folders, one file per change   FOLDERS_DIR_NAME
    templates/HCR drawing.drwdot      the org's and projects' SolidWorks templates    TEMPLATES_DIR_NAME
    templates/templates.yaml          which template is which, and the defaults       TEMPLATES_INDEX
    .litterbox/config.yaml            shared vault settings               CONFIG_PATH (CONFIG_DIR, CONFIG_FILE)
    .litterbox/people.yaml            the team                            PEOPLE_FILE
    .litterbox/workflows.yaml         sign-off templates                  WORKFLOWS_FILE
    .litterbox/document_types.yaml    the org's document types            DOC_TYPES_FILE
    .litterbox/allowed_signers        generated from people.yaml          ALLOWED_SIGNERS_FILE
    .litterbox/whoami                 a lock used to learn who you are    WHOAMI_FILE

Changing any of these changes the vault format (see version.VAULT_FORMAT).
"""

LOG_DIR_NAME = "PN-logs"
CAD_DIR_NAME = "cad"
CANCELLED_DIR_NAME = f"{CAD_DIR_NAME}/cancelled-revs"    # revisions that were cancelled before release are kept here
LEGACY_CANCELLED_DIR_NAME = "cancelled-revs"   # where they were kept before 0.6.3
CANCELLED_PREFIX = "CANCELLED_"
ECO_DIR_NAME = "ECO"                         # engineering change orders (change_orders/)
DOC_LOG_DIR_NAME = "DOC-logs"                # document records (documents/), like PN-logs for parts
DOC_DIR_NAME = "documents"                   # documents' files, like cad for parts
TOOLBOX_DIR_NAME = "toolbox"                 # the team's Toolbox (vault/toolbox_admin.py): only Admins change it
FOLDERS_DIR_NAME = "folders"                 # Team and project folders (folders/folder_store.py): one file per change
TEMPLATES_DIR_NAME = "templates"             # SolidWorks templates new files are made from (vault/template_store.py)
TEMPLATES_INDEX = f"{TEMPLATES_DIR_NAME}/templates.yaml"

CONFIG_DIR = ".litterbox"
CONFIG_FILE = "config.yaml"                 # a file name inside CONFIG_DIR (the others below are paths)
CONFIG_PATH = f"{CONFIG_DIR}/{CONFIG_FILE}"
PEOPLE_FILE = f"{CONFIG_DIR}/people.yaml"
WHOAMI_FILE = f"{CONFIG_DIR}/whoami"
ALLOWED_SIGNERS_FILE = f"{CONFIG_DIR}/allowed_signers"
WORKFLOWS_FILE = f"{CONFIG_DIR}/workflows.yaml"
DOC_TYPES_FILE = f"{CONFIG_DIR}/document_types.yaml"
