"""
number_input.py - reading numbers typed into dialogs (part numbers, digit counts, start number) with
plain-language problems, and the variant list.
"""

from litterbox.core import part_number


def import_base_placeholder(repo, org, project=None):
    """The base number the Import window's 'same base number' box suggests: what New Part would pick (in
    `project`, a project's name, or outside every project's block)."""
    from litterbox.parts import number_suggestions
    try:
        return part_number.format_base(number_suggestions.suggest_part_number(repo, org, project))
    except Exception:
        return ""


def parse_number(text, label, minimum=1, maximum=None):
    """A whole number typed into a box. Raises ValueError with a message safe to show."""
    text = str(text or "").strip()
    if not text:
        raise ValueError(f"Enter the {label}.")
    if not (text.isascii() and text.isdigit()):
        raise ValueError(f"The {label} must be a whole number, like 42.")
    number = int(text)
    if number < minimum:
        raise ValueError(f"The {label} must be {minimum} or higher.")
    if maximum is not None and number > maximum:
        raise ValueError(f"The {label} can be at most {maximum}.")
    return number


def parse_typed_number(text, label, digits):
    """A number typed into the part number or variant box, which must be written exactly.

    An empty box gives None (use the suggested number). Otherwise the text must
    be exactly `digits` plain digits, so with 5 digits "00002" is accepted but
    "2" and "000002" are not. Raises ValueError with a message safe to show.
    """
    text = str(text or "").strip()
    if not text:
        return None
    example = f"{1:0{digits}d}"
    if not (text.isascii() and text.isdigit()) or len(text) != digits:
        raise ValueError(f"The {label} must be exactly {digits} digits, like {example}.")
    number = int(text)
    if number < 1:
        raise ValueError(f"The {label} can't be {text}. The lowest is {example}.")
    return number


def parse_digit_count(text, label, low, high):
    """The number of digits typed in the org setup. Raises ValueError with a message safe to show."""
    text = str(text or "").strip()
    if not (text.isascii() and text.isdigit()) or not (low <= int(text) <= high):
        raise ValueError(f"The {label} must be a whole number from {low} to {high}.")
    return int(text)



def parse_project_number(text, project):
    """The digits typed after a project's prefix in the New Part box, as the whole part number ('0034' with prefix
    12 gives 120034), or None for an empty box. Raises ValueError with a message safe to show."""
    text = str(text or "").strip()
    if not text:
        return None
    digits = project.remaining_digits()
    if not (text.isascii() and text.isdigit()) or len(text) != digits:
        raise ValueError(f"After {project.prefix}, the part number needs exactly {digits} more digits, "
                         f"like {1:0{digits}d}.")
    number = project.full_base(int(text))
    if number < part_number.MIN_BASE:
        raise ValueError(f"The part number can't be {project.prefix}{text}. The lowest is "
                         f"{part_number.format_base(project.block()[0])}.")
    return number


def in_use_text(check):
    """The line shown under "PN in use:": the name of the part that has the number."""
    text = check.name or "(no name)"
    return text + (" (void)" if check.status == "void" else "")


