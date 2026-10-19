"""
person_name.py - PersonName: a person's name as Litterbox writes it in the history ("by": Alex Smith), carrying
their id on the team list ("by_id": alex) so their actions stay theirs if their name changes.

repository.get_user hands one out; anything that writes "by" (or "requested_by", "created_by") writes the id
beside it with stamp(). The id is "" when there is no team list, or you aren't verified on it.
"""

import yaml


class PersonName(str):
    """A name (it is the str) with the person's team id as .id ("" when not known)."""

    def __new__(cls, name, person_id=""):
        value = super().__new__(cls, name)
        value.id = str(person_id or "")
        return value


def id_of(name):
    """The team id carried by a name ("" for a plain str)."""
    return getattr(name, "id", "")


def stamp(entry, key, name):
    """Put `name` in entry[key] (as plain text) and its id in entry[key + '_id'] when it has one. Returns entry."""
    entry[key] = str(name)
    if id_of(name):
        entry[f"{key}_id"] = id_of(name)
    return entry


# Written as plain text, never as a Python object, if one reaches a YAML file directly.
yaml.SafeDumper.add_representer(PersonName, lambda dumper, value: dumper.represent_str(str(value)))
