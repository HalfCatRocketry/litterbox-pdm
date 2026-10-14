"""
permission_check.py - the check every action that
changes a part makes first: does this person's role allow it? (See team/people.py.)
"""



def check_permission(repo, user, action):
    """Stop the action unless this user's role allows it.

    Every action that changes something calls this first. `action` is one of:
    create, checkout, checkin, undo, edit_details, release, make_cots, revise,
    cancel_revision, reopen, void (and manage_people / transfer_owner in people.py).
    In a vault with a people file, only active team members pass (see people.py); a vault
    without one lets everybody do everything.
    """
    from litterbox.team import people
    people.require(repo, action)
