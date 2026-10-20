"""
purchasing_info.py - a part's purchasing information: supplier, supplier part number, unit cost and lead time.

It belongs to the part, not to a revision (a price changes without the design changing), and it is kept in the
record as an optional section that older Litterbox versions keep without reading:

    purchasing:
      supplier: McMaster-Carr
      supplier_pn: '91251A540'
      unit_cost: '0.42'          text, so 0.10 stays 0.10; in the team's own currency
      lead_time_days: 3

Empty fields are left out, and so is the whole section when every field is empty. Fields a newer Litterbox adds
to the section are kept as they are.
"""

import re

SUPPLIER, SUPPLIER_PN, UNIT_COST, LEAD_TIME_DAYS = "supplier", "supplier_pn", "unit_cost", "lead_time_days"
FIELDS = (SUPPLIER, SUPPLIER_PN, UNIT_COST, LEAD_TIME_DAYS)
LABELS = {SUPPLIER: "Supplier", SUPPLIER_PN: "Supplier part number", UNIT_COST: "Unit cost",
          LEAD_TIME_DAYS: "Lead time (days)"}

MAX_TEXT = 100
MAX_LEAD_TIME_DAYS = 3650
MAX_COST_DECIMALS = 4
COST = re.compile(r"^(\d+(\.\d*)?|\.\d+)$")


class PurchasingError(ValueError):
    """A purchasing field is wrong. The message is safe to show."""


def _text(value, label):
    text = " ".join(str(value if value is not None else "").split())
    if len(text) > MAX_TEXT:
        raise PurchasingError(f"{label} can be at most {MAX_TEXT} characters.")
    return text


def clean_cost(value):
    """'$1,234.5' -> '1234.5'; '' -> ''. A number of at least zero with at most four decimals."""
    text = str(value if value is not None else "").strip().replace(",", "").lstrip("$€£¥").strip()
    if not text:
        return ""
    if text.startswith("-"):
        raise PurchasingError("Unit cost must be zero or more.")
    if not COST.match(text):
        raise PurchasingError(f"Unit cost must be a number, like 12.50 (not '{value}').")
    if len(text.partition(".")[2]) > MAX_COST_DECIMALS:
        raise PurchasingError(f"Unit cost can have at most {MAX_COST_DECIMALS} decimal places.")
    text = text.rstrip(".") if text.endswith(".") else text
    return ("0" + text) if text.startswith(".") else text


def clean_lead_time(value):
    """'14' -> 14; '' -> None. Whole days, 0 to 3650."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise PurchasingError("Lead time must be a whole number of days.")
    try:
        days = int(str(value).strip())
    except ValueError:
        raise PurchasingError(f"Lead time must be a whole number of days (not '{value}').") from None
    if not 0 <= days <= MAX_LEAD_TIME_DAYS:
        raise PurchasingError(f"Lead time must be between 0 and {MAX_LEAD_TIME_DAYS} days.")
    return days


def clean(data):
    """The section as it is stored: known fields checked and tidied, empty ones left out, unknown ones kept.
    Raises PurchasingError."""
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PurchasingError("'purchasing' must be a list of fields (supplier, unit_cost, ...).")
    cleaned = {}
    for key in (SUPPLIER, SUPPLIER_PN):
        text = _text(data.get(key), LABELS[key])
        if text:
            cleaned[key] = text
    cost = clean_cost(data.get(UNIT_COST))
    if cost:
        cleaned[UNIT_COST] = cost
    days = clean_lead_time(data.get(LEAD_TIME_DAYS))
    if days is not None:
        cleaned[LEAD_TIME_DAYS] = days
    cleaned.update({k: v for k, v in data.items() if k not in FIELDS})
    return cleaned


def shown(section, key):
    """A field as text for a window or a spreadsheet ('' when empty)."""
    value = (section or {}).get(key)
    return "" if value is None else str(value)


def changes(old, new):
    """What changed between two cleaned sections, for the history: ["supplier: '' -> 'McMaster-Carr'", ...]."""
    return [f"{LABELS[key].lower()}: '{shown(old, key)}' -> '{shown(new, key)}'"
            for key in FIELDS if shown(old, key) != shown(new, key)]
