"""
com.py - talking to SolidWorks over COM.

The small helpers every SolidWorks feature needs: attaching to (or starting) SolidWorks, and calling a member
that may turn out to be a property or a method. The experiments in tools/solidworks use these too.
"""


def call(obj, name, *args):
    """Read a SolidWorks property or call a method, whichever `name` turns out to be.

    Through Python's COM bridge some SolidWorks members behave like properties
    and some like methods, and it is not always obvious which; this handles both.
    """
    attribute = getattr(obj, name)
    return attribute(*args) if callable(attribute) else attribute


def connect():
    """Attach to a running SolidWorks, or start one. Returns (sw, started_by_us)."""
    import win32com.client
    try:
        return win32com.client.GetActiveObject("SldWorks.Application"), False
    except Exception:
        return win32com.client.Dispatch("SldWorks.Application"), True
