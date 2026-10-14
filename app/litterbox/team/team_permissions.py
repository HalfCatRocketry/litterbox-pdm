"""
team_permissions.py - may this person do this action? (require), and who may change whom.

These checks are process control, not security: someone with push access can bypass Litterbox.
"""

from litterbox.errors import LitterboxError
from litterbox.team import team_identity
from litterbox.team import team_model


def require(repo, action):
    """Raise LitterboxError unless the current user may do `action`. Returns the Identity."""
    identity = team_identity.current(repo)
    allowed, why = identity.allows(action)
    if not allowed:
        raise LitterboxError(why)
    return identity


def rank(access):
    return {team_model.OWNER: 3, team_model.ADMIN: 2, team_model.MEMBER: 1}.get(access, 0)


def may_change(actor, target):
    """Owners may change anyone but themselves-as-owner rules below; Admins may change Members only."""
    if actor.access == team_model.OWNER:
        return True
    return actor.access == team_model.ADMIN and target.access == team_model.MEMBER
