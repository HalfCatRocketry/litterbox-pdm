"""
com.py - talking to SolidWorks over COM.

The small helpers every SolidWorks feature needs: attaching to (or starting) SolidWorks, and calling a member
that may turn out to be a property or a method. The experiments in tools/solidworks use these too.
"""

import contextlib


@contextlib.contextmanager
def com_thread():
    """SolidWorks is reached through COM, which must be switched on in the thread that uses it."""
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:                                   # not Windows, or no pywin32 (tests)
        pythoncom = None
    try:
        yield
    finally:
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


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


def show_hidden_solidworks():
    """If a SolidWorks is running but hidden (one that a program started and that never closed), show it.

    Opening a file hands it to the SolidWorks that is already running, so without this the part would
    load into a window that can't be seen. Returns True if it had to show one. Never raises."""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            sw = win32com.client.GetActiveObject("SldWorks.Application")
            hidden = not sw.Visible
            if hidden:
                sw.Visible = True
            del sw
            return hidden
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return False
