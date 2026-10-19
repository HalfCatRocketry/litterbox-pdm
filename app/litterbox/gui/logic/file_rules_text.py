"""
file_rules_text.py - what the window says about the vault's file rules (.gitattributes, see
vault/git_attributes.py): the question before updating them, and the messages around it.
"""


ASK_AN_ADMIN = ("This vault's file rules are older than this Litterbox's. An Admin or the Owner can update them "
                "(Vault > Update file rules...).")


def question(found, newest, lines, raises_minimum=False, minimum=""):
    """The question before an update. found: the vault's rules version (None: it has none, 0: from Litterbox 0.4.1
    or older); lines: the rules that would be added (git_attributes.change_lines)."""
    if found is None:
        state = "This vault has none of Litterbox's file rules."
    elif found == 0:
        state = "This vault's file rules come from Litterbox 0.4.1 or older."
    else:
        state = f"This vault has file rules version {found}; this Litterbox has version {newest}."
    text = [state, "", "The rules say which files Git LFS stores and which files can be locked (checked out). "
                       "Updating changes only Litterbox's own lines in .gitattributes."]
    if lines:
        text += ["", "Rules to add:", *lines]
    else:
        text += ["", "No rules are added: Litterbox's lines are only marked so later versions can update them."]
    text += ["", "Files already in the vault that a new rule covers are converted in the same upload."]
    if raises_minimum:
        text += ["", f"Some new rules lock files, so everyone will need Litterbox {minimum} or newer to work in "
                     "this vault."]
    text += ["", "Update the file rules now? The change is uploaded for everyone."]
    return "\n".join(text)


def done_text(added):
    return f"File rules updated ({added} rule{'s' if added != 1 else ''} added)" if added else "File rules updated"
