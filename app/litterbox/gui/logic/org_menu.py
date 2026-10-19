"""
org_menu.py - the orgs: the org box in the header, the orgs you have, moving old settings over, Add org planning,
Create new org text, and checking a folder looks like a vault. An org's code and numbering are fixed when its vault
is created, so there is nothing here to change them (the Owner changes the name in Vault Settings).
"""

from pathlib import Path

from litterbox.gui.logic import error_text


ADD_ORG = "Add org..."


CREATE_VAULT = "Create new org..."



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


def org_choices(data):
    """The header's org box: every known org ("No org" when there are none). Adding and setting up orgs is in the
    File menu."""
    return list(known_orgs(data)) or ["No org"]


CREATE_VAULT_INTRO = (
    "A new vault starts as an empty repository on your Git host (Azure DevOps, GitHub or GitLab).\n\n"
    "1. Create the empty repository on the host (with no README or other files).\n"
    "2. Press its Clone button and copy the https address.\n\n"
    "Litterbox will then copy it to this computer, add its settings, upload them, and make you the team's Owner. "
    "Have you created the empty repository?")


def default_start(base_digits):
    """The part number Create new org... suggests starting with: 1, then 0s, then 1, as wide as the base (100001
    for 6 digits; 1 for 1 digit)."""
    return 1 if base_digits <= 1 else 10 ** (base_digits - 1) + 1


def example_number(base_digits, variant_digits):
    """What a part number looks like with these digits, shown beside the digit boxes: 123456-001 for 6 and 3."""
    base = "".join(str(i % 10) for i in range(1, base_digits + 1))
    return f"{base}-{1:0{variant_digits}d}"


def fixed_settings_text(org, org_name, start, base_digits, variant_digits, warnings=(), assembly_variant=None):
    """The last question before Create new org... goes ahead: the org code and part number scheme can never be
    changed in Litterbox (the Owner can change the org name later)."""
    example = f"{org}-{start:0{base_digits}d}-{1:0{variant_digits}d}"
    lines = [
        "Check these carefully. Once the organization is created, Litterbox can't change them:",
        "",
        f"    Organization code:  {org}",
        f"    Part numbers:  {base_digits} digits and a {variant_digits}-digit variant",
        f"    First part number:  {example}",
        "",
        f"Organization name:  {org_name or '(none)'} (the Owner can change this later)",
    ]
    if assembly_variant is not None:
        lines += [f"Assembly variant number start:  {assembly_variant:0{variant_digits}d} (an Admin can change "
                  "this later)"]
    if warnings:
        lines += [""] + list(warnings)
    lines += ["", "Create the organization?"]
    return "\n".join(lines)


def vault_created_text(result):
    """What to tell the user after init_vault.create() worked. `result` is an init_vault.InitResult."""
    lines = [f"The {result.org} vault is set up" + (" and uploaded." if result.pushed else " on this computer only.")]
    if result.owner is not None:
        lines.append(f"{result.owner.name} is the team's Owner.")
    elif result.team_error:
        lines.append("The team could not be set up just now, so everyone can still do everything. "
                     f"Use the Team screen to set it up later.\n\n{error_text.shorten(result.team_error)}")
    lines.extend(result.warnings)
    return "\n\n".join(lines)


def plan_add_org(url, root, known):
    """What Add org... (or Create new org...) will do with the URL the user pasted: (folder to clone into,
    problem). `known` is the {org: folder} Litterbox already has, so a vault that is already added is said so, not
    cloned again. One whose folder has gone missing is cloned again. A folder Litterbox isn't allowed to look in is
    reported as the problem, not raised."""
    from litterbox.vault import clone as vault_clone
    name, problem = vault_clone.parse_url(url)
    if problem:
        return None, problem
    target = vault_clone.target_folder(root, name)
    for org, folder in known.items():
        if str(Path(folder)).lower() != str(target).lower():
            continue
        try:
            there = target.exists()
        except OSError as e:
            return None, (f"Litterbox isn't allowed to look in {target}, where {org} should be ({e.strerror or e}). "
                          "Check that your Windows account can open that folder, then try again.")
        if there:
            return None, f"{org} is already added: it is in {target}. Choose it from the org box at the top."
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
                    "If it is a new, empty repository, use Create new org... instead.")
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
