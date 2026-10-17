"""
text_fit.py - cutting text to a width with "..." (an ellipsis), for the parts list's long columns. `measure(text)`
gives a text's width in pixels in the list's font; the window passes it in.
"""

ELLIPSIS = "…"


def one_line(text):
    """Line breaks and runs of spaces become single spaces: a list row shows one line."""
    return " ".join(str(text or "").split())


def fit(text, width, measure):
    """The text, shortened with an ellipsis if it is wider than `width` pixels."""
    text = one_line(text)
    if not text or width <= 0 or measure(text) <= width:
        return text
    low, high = 0, len(text)                        # the longest start that still fits with the ellipsis
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle].rstrip() + ELLIPSIS) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + ELLIPSIS if low else ELLIPSIS
