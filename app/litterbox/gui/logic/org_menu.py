"""
org_menu.py - the org box in the header: the orgs you have, moving old settings over, Add org planning,
Create new vault text, and checking a folder looks like a vault.
"""

from pathlib import Path

from litterbox.gui.logic import error_text


ADD_ORG = "Add org..."


CREATE_VAULT = "Create new vault..."


EDIT_ORG = "Org setup..."


def known_orgs(data):
    """{org code: vault folder} from the personal settings. Bad entries are ignored."""
    orgs = data.get("orgs")
    if not isinstance(orgs, dict):
        return {}
    return {str(code).upper(): str(path) for code, path in orgs.items() if code and path}


def migrate_settings(data, detect_org):
    """Older settings only had one 'repo'. Turn it into an org entry.

    detect_org(folder) returns the folder's org code, or None if it can't tell.
    Returns True if the settings changed.
    """
    if known_orgs(data) or not data.get("repo"):
        return False
    code = detect_org(data["repo"])
    if not code:
        return False
    data["orgs"] = {code: data["repo"]}
    data["last_org"] = code
    return True


def current_org(data):
    """The org to open: the last one worked on if it is still known, else the first known one."""
    orgs = known_orgs(data)
    last = str(data.get("last_org") or "").upper()
    if last in orgs:
        return last
    return next(iter(orgs), None)


def org_menu_values(data):
    """The dropdown entries: every known org, then the two setup actions."""
    return list(known_orgs(data)) + [ADD_ORG, CREATE_VAULT, EDIT_ORG]


CREATE_VAULT_INTRO = (
    "A new vault starts as an empty repository on your Git host (Azure DevOps, GitHub or GitLab).\n\n"
    "1. Create the empty repository on the host.\n"
    "2. Clone it to this computer (for example into C:\\Litterbox).\n"
    "3. Come back here and choose the cloned folder.\n\n"
    "Litterbox will then add its settings, upload them, and make you the team's Owner. "
    "Have you cloned the empty repository?")


def vault_created_text(result):
    """What to tell the user after init_vault.create() worked. `result` is an init_vault.InitResult."""
    lines = [f"The {result.org} vault is set up" + (" and uploaded." if result.pushed else " on this computer only.")]
    if result.owner is not None:
        lines.append(f"{result.owner.name} is the team's Owner.")
    elif result.team_error:
        lines.append("The team could not be set up just now, so everyone can still do everything. "
                     f"Use Team... to set it up later.\n\n{error_text.shorten(result.team_error)}")
    lines.extend(result.warnings)
    return "\n\n".join(lines)


def plan_add_org(url, root, known):
    """What Add org... will do with the URL the user pasted: (folder to clone into, problem). `known` is the
    {org: folder} Litterbox already has, so a vault that is already added is said so, not cloned again."""
    from litterbox.vault import clone as vault_clone
    name, problem = vault_clone.parse_url(url)
    if problem:
        return None, problem
    target = vault_clone.target_folder(root, name)
    for org, folder in known.items():
        if str(Path(folder)).lower() == str(target).lower():
            return None, f"{org} is already added: it is in {target}. Choose it from the box next to the title."
    return target, ""


def inspect_vault_folder(folder):
    """Look at a folder the user chose for Add org... Returns (org code, "") if it is a Litterbox vault, or
    ("", what is wrong and what to do about it)."""
    from litterbox.vault import compatibility
    from litterbox.vault import config
    path = Path(folder)
    if not path.is_dir():
        return "", "That folder doesn't exist."
    if not (path / ".git").exists():
        return "", ("That folder isn't a git repository. Clone your vault first (the clone is the vault folder), "
                    "then choose it here.")
    try:
        compatibility.check_compatible(path)
        return config.get_org(path), ""
    except config.NoOrgError:
        return "", ("That repository isn't a Litterbox vault yet: it has no .litterbox/config.yaml and no parts. "
                    "If it is a new, empty repository, use Create new vault... instead.")
    except config.ConfigError as e:
        return "", str(e)


def remember_org(data, org, folder):
    """Add or update an org and make it the last one worked on."""
    orgs = known_orgs(data)
    orgs[org.upper()] = str(folder)
    data["orgs"] = orgs
    data["last_org"] = org.upper()
    data["repo"] = str(folder)            # kept so older copies of the app still open something
    return data
