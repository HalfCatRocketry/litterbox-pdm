"""
download_text.py - what the window says about downloading CAD files on demand (see parts/downloads.py).
"""

DOWNLOAD_ALL_QUESTION = ("Download every CAD file in this vault?\n\n"
                         "Litterbox normally downloads a part's files only when you check it out or open it. Download "
                         "All gets everything now, which can be a lot of data, and Get Latest then keeps it all up to "
                         "date.\n\nTo make this the default, add  download: all  to C:\\Litterbox\\settings.yaml.")


def _files(count):
    return "1 file" if count == 1 else f"{count} files"


def downloading_label(pn, count):
    """What the banner says while a part's files are downloaded before opening it."""
    return f"Downloading {_files(count)} for {pn.short}"


def downloaded_for_open(pn, revision, count):
    return f"Downloaded {_files(count)} for {pn.short} Rev {revision}"
