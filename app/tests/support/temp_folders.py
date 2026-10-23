"""
Removing a test's temporary folder completely, read-only files and all.

shutil.rmtree(..., ignore_errors=True) leaves read-only files behind on Windows (vault files Litterbox made
read-only, and git's own objects), so every git test used to leave its vault in the temp folder. remove() makes a
file writable and tries again; anything still in the way is left, never raised.
"""

import os
import shutil
import stat


def remove(folder):
    """Delete the folder and everything in it, read-only files too. Never raises."""
    def writable_and_again(func, path, _error):
        try:
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    try:
        shutil.rmtree(folder, onexc=writable_and_again)
    except OSError:
        pass
