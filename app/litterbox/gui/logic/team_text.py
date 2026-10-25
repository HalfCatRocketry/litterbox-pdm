"""
team_text.py - the Team window: the people table, the identity banner, Who am I, the person form, roles,
and which vault settings changed.
"""

from litterbox import version
from litterbox.core import project_settings
from litterbox.core import toolbox_rules


def person_unchanged(person, fields):
    """True if the Edit Person form's fields (from person_form_result) are what the person already has."""
    return (fields.get("name") == person.name and fields.get("email", "") == person.email
            and list(fields.get("host_names", [])) == list(person.host_names)
            and fields.get("access", person.access) == person.access
            and list(fields.get("roles", [])) == list(person.roles)
            and list(fields.get("signing_keys", [])) == list(person.signing_keys))


def identity_banner(identity):
    """(text, tone) for the line under the title. tone is 'normal' or 'warn'."""
    text = identity.describe()
    return text, ("normal" if identity.state in ("ok", "legacy") else "warn")


def people_table(directory):
    """Rows for the Team window: (id, (name, email, access, roles, active, host names, keys))."""
    rows = []
    for p in directory.people:
        rows.append((p.id, (p.name, p.email, p.label, ", ".join(p.roles), "Yes" if p.active else "No",
                            ", ".join(p.host_names), len(p.signing_keys) or "")))
    return rows


def person_details(person):
    """The line under the Team screen's list for the highlighted person: what the table leaves out."""
    keys = len(person.signing_keys)
    parts = [f"{person.name} ({person.id}): {person.label}" + ("" if person.active else ", switched off"),
             "Roles: " + (", ".join(person.roles) or "none"),
             "Host names: " + (", ".join(person.host_names) or "none"),
             "Signing keys: " + (str(keys) if keys else "none")]
    return "     ".join(parts)


def split_list(text):
    """'a, b\nc' -> ['a', 'b', 'c'] (commas or new lines)."""
    return [part.strip() for part in str(text or "").replace("\n", ",").split(",") if part.strip()]


def suggest_person_id(name, existing):
    """A short lowercase id from a name ('Alex Smith' -> 'alex-smith'), made unique among `existing`."""
    import re
    base = re.sub(r"[^a-z0-9._-]+", "-", str(name).lower()).strip("-.")[:36] or "person"
    taken = {str(e).lower() for e in existing}
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    return candidate


def who_am_i_text(identity):
    lines = [f"The host says you are signed in as: {identity.host_name or '(unknown)'}"]
    if identity.state == "legacy":
        lines.append("This vault has no team list yet, so everyone can do everything.")
    elif identity.state == "ok":
        p = identity.person
        lines.append(f"That matches {p.name} on the team list: {p.label}"
                     + (f", {', '.join(p.roles)}" if p.roles else "") + ".")
    else:
        lines.append(identity.message())
    return "\n\n".join(lines)


def person_form_result(old_id, form, existing_ids):
    """Check the Add/Edit Person form. Returns (problem text, fields dict). `form` has name, email,
    host_names, roles, keys, id and access (all text)."""
    name = " ".join(str(form.get("name", "")).split())
    if not name:
        return "Enter a name.", {}
    email = str(form.get("email", "")).strip()
    if email and "@" not in email:
        return "That doesn't look like an email address.", {}
    fields = {"name": name, "email": email, "host_names": split_list(form.get("host_names")),
              "roles": split_list(form.get("roles")), "signing_keys": [line.strip() for line in str(form.get("keys", "")).splitlines() if line.strip()],
              "access": str(form.get("access", "member")).strip().lower()}
    if old_id is None:
        fields["id"] = str(form.get("id", "")).strip().lower() or suggest_person_id(name, existing_ids)
    return "", fields


def add_role_result(text, roles):
    """Check a role typed into the Roles window. Returns (problem, tidy role name)."""
    role = " ".join(str(text or "").split())
    if not role:
        return "Type a role first.", ""
    if "," in role:
        return "A role can't contain a comma.", ""
    if role.lower() in (r.lower() for r in roles):
        return f"'{role}' is already on the list.", ""
    return "", role


def role_removal_text(role, holders):
    if not holders:
        return f"Remove the role '{role}' from the list?"
    names = ", ".join(holders[:8]) + (f" and {len(holders) - 8} more" if len(holders) > 8 else "")
    return (f"Remove the role '{role}'?\n\nIt will also be taken off everyone who has it ({names}). "
            "This happens when you press Save.")


def roles_to_choose(all_roles, chosen):
    """The roles a person doesn't have yet, for the drop-down."""
    have = {r.lower() for r in chosen}
    return [r for r in all_roles if r.lower() not in have]


def changed_settings(current, chosen):
    """The vault settings in `chosen` (from the Vault Settings dialog) that differ from `current`. {} if none."""
    if not chosen:
        return {}
    return {key: value for key, value in chosen.items() if current.get(key) != value}


def project_settings_prompt(changes):
    """The "Are you sure?" before the project settings (core/project_settings.py) are turned on; "" when the
    changes don't turn one on."""
    lines = []
    if changes.get("project_creators") == project_settings.ANYONE:
        lines.append("Anyone on the team will be able to add a project, and becomes its Lead.")
    if changes.get("project_min_digits"):
        lines.append(f"A new project will need at least {changes['project_min_digits']} starting digits: Admins and "
                     "the Owner are warned about fewer, anyone else is refused. Projects already made keep theirs.")
    if not lines:
        return ""
    return " ".join(lines) + (f"\n\nEveryone will also need Litterbox {project_settings.MIN_LITTERBOX} or newer, "
                              "since older versions don't keep to these settings.")


def toolbox_rule_prompt(rule):
    """The "Are you sure?" before the vault's Toolbox rule (core/toolbox_rules.py) is set to `rule` (not OFF)."""
    if rule == toolbox_rules.TEAM:
        what = ("From now on, an assembly may use Toolbox parts only from the team's Toolbox, which an Admin keeps "
                "in the vault (Team > Toolbox...), and no other files from outside the vault.")
    else:
        what = ("From now on, an assembly may not use Toolbox parts, or any other file from outside the vault: model "
                "each fastener as a part of its own.")
    return (what + " Check In refuses an assembly that does, and so does Release. An assembly last checked in "
            "without SolidWorks needs Update BOM before it can be released."
            f"\n\nEveryone will also need Litterbox {toolbox_rules.MIN_LITTERBOX} or newer, since older versions "
            "don't check this.\n\nSet it?")


def solidworks_version_prompt(year, installed):
    """The "Are you sure?" before the org's SolidWorks version is set to `year`. `installed` is this computer's
    (None without one)."""
    text = (f"From now on, everyone works in SolidWorks {year}. Anyone whose SolidWorks is newer can't check out, "
            "revise, import or change references until they use "
            f"{year}, or the version here is changed.")
    if installed and installed > year:
        text += f"\n\nYour own SolidWorks is {installed}, so that includes you."
    text += (f"\n\nEveryone will also need Litterbox {version.VERSION} or newer, since older versions don't check "
             "this.\n\nSet it?")
    return text
