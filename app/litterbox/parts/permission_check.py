"""
permission_check.py - the checks an action that changes a part makes first: does this person's role allow it?
(See team/people.py.) Is the part in a restricted project they aren't a member of? (See team/project_access.py.) And, for the actions that save SolidWorks files, is this computer's SolidWorks newer than the
org's? (See cad/solidworks_versions.py.)
"""

from litterbox.cad import solidworks_versions
from litterbox.errors import LitterboxError
from litterbox.vault import config


def check_permission(repo, user, action):
    """Stop the action unless this user's role allows it.

    Every action that changes something calls this first. `action` is one of:
    create, checkout, checkin, undo, edit_details, release, make_cots, revise,
    cancel_revision, reopen, void, edit_purchasing (and manage_people / transfer_owner in people.py).
    In a vault with a people file, only active team members pass (see people.py); a vault
    without one lets everybody do everything.
    """
    from litterbox.team import team_permissions
    team_permissions.require(repo, action)


def project_refusals(repo, items):
    """{pn: why} for the parts of a batch ([(pn, permission)]) in restricted projects this user may not work on."""
    from litterbox.team import project_access
    return project_access.refused(repo, items)


def check_new_number(repo, project):
    """Stop making a part number in this project (its name; '' for none) if it is restricted to others."""
    from litterbox.team import project_access
    if project:
        project_access.require_work(repo, [project], f"make part numbers in project {project}")


def check_parts(repo, pns, action):
    """Stop the action if any of these parts is in a restricted project this user may not work on (a part is in
    the project whose block holds its number)."""
    from litterbox.core.part_number import PNError
    from litterbox.parts import batch_core
    from litterbox.team import project_access
    try:
        pns = [batch_core.as_pn(pn) for pn in pns]
    except PNError:
        return                                      # the action itself says what is wrong with the number
    project_access.require_parts(repo, pns, action)


def uses_solidworks(repo, pns):
    """True if any of these is a CAD part (non-CAD parts never open SolidWorks). A record that can't be read
    counts as CAD, so the check still happens."""
    from litterbox.records import record_model
    from litterbox.records import record_store
    for pn in pns:
        try:
            if record_store.load(repo, pn).uses_cad:
                return True
        except record_model.RegistryError:
            return True
    return False


def check_solidworks_version(repo, action):
    """Stop the action if this computer's SolidWorks is newer than the version the org works in: whatever it
    saved could not be opened by anyone else. `action` is like 'check out HCR-00042-001'. A vault with no version
    set, or a computer without SolidWorks, always passes."""
    org_year = config.get_solidworks_version(repo)
    if not org_year:
        return
    installed = solidworks_versions.installed_year()
    if solidworks_versions.compare(org_year, installed) == solidworks_versions.NEWER:
        raise LitterboxError(solidworks_versions.blocked_text(org_year, installed, action))
