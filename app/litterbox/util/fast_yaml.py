"""
fast_yaml.py - reading YAML quickly: PyYAML's C parser (libyaml) when this PyYAML has it, its own Python parser
otherwise.

Both read a file to the same values, and both are safe loaders (never plain yaml.load). The C one is several times
faster, which the parts list feels on every refresh: it reads one record file per part. If the C parser fails, the
Python one reads the text again, so a damaged file is described in the same words as it always was.

Writing stays with yaml.safe_dump everywhere, so the files Litterbox writes don't change by a byte.
"""

import yaml

_FAST_LOADER = getattr(yaml, "CSafeLoader", None)


def safe_load(stream):
    """yaml.safe_load(stream): `stream` is text or an open file. Raises yaml.YAMLError as safe_load does."""
    if _FAST_LOADER is None:
        return yaml.safe_load(stream)
    text = stream if isinstance(stream, (str, bytes)) else stream.read()
    try:
        return yaml.load(text, Loader=_FAST_LOADER)       # a safe loader: the C twin of yaml.SafeLoader
    except yaml.YAMLError:
        return yaml.safe_load(text)                       # the Python parser's own words for what is wrong
