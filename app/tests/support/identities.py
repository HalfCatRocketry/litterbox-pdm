"""A ready-made team identity for the workflow tests. No tests here."""

from types import SimpleNamespace
from litterbox.team import team_identity
from litterbox.team import team_model


def identity_for(person_id, directory, access=team_model.MEMBER):
    person = directory.get(person_id)
    return SimpleNamespace(state=team_identity.OK, person=person, directory=directory)
