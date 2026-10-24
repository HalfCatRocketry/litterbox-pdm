"""
configuration_names.py - naming a part's configuration after the part: a model whose only configuration is called
"Default" has it renamed to the part's Name, so an assembly's tree shows HCR-00042-001_A<1> (Bracket) the way
McMaster-Carr's parts show their catalogue number. When the Name changes, the configuration Litterbox named is
renamed again.

Only a file with ONE configuration is touched, and only when that configuration is "Default" or the name Litterbox
gave it before: a file someone set up with configurations of their own is left alone. Assemblies follow a renamed
configuration (SolidWorks keeps an ID for each, seen with SolidWorks 2024), so nothing that uses the part breaks.

SolidWorks refuses "/" and "@" in a configuration's name (and names that start or end with a space): they become
"-" here.
"""

DEFAULT = "Default"
MAX_LENGTH = 100
_REFUSED = "/@"


def clean(name):
    """The part's Name as a configuration may be called: refused characters made "-", spaces tidied, at most
    MAX_LENGTH characters. "" if nothing is left."""
    text = "".join("-" if ch in _REFUSED else ch for ch in str(name or ""))
    return " ".join(text.split())[:MAX_LENGTH].strip()


def rename(own_names, named_before, part_name):
    """(old, new) when the model's configuration should be renamed after the part, else None. `own_names` are the
    model's configurations, `named_before` the name Litterbox gave it last time ("" for none)."""
    if len(own_names) != 1:
        return None
    current, wanted = own_names[0], clean(part_name)
    if not wanted or current == wanted:
        return None
    if current == DEFAULT or (named_before and current == named_before):
        return current, wanted
    return None
