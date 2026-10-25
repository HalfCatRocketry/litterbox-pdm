"""
bug_report_text.py - what Help > Report a problem says (the report itself is user/bug_report.py, sending it
user/report_mail.py): the window's words, and what to say once the email is open.
"""

PROMPT = "Briefly explain what you were doing at the time of the error"
NEEDS_COMMENT = "Please say briefly what you were doing, so the problem can be found."
CONTENTS_HEADING = "What goes in the report"
INCLUDE_LOG = "Include Litterbox's log (often how the problem is found)"
INCLUDE_SETTINGS = "Include your Litterbox settings and this vault's shared settings"
OPEN_QUESTION = "Open the report to look at it before you send it?"


def intro(address, problems):
    """The text at the top of the window. `problems` is how many problems the red status bar holds."""
    which = (f" The {problems} problem{'s' if problems != 1 else ''} in the red status bar go{'es' if problems == 1 else ''} "
             "in too." if problems else "")
    return (f"This makes a report for the Litterbox team and opens an email to {address} with it, for you to "
            f"send.{which} Nothing is sent until you press Send, and you can open the report first.")


def size_text(size):
    """'about 12 KB' for a file's size in bytes; '' when not known (report.txt is written as the report is made)."""
    if size is None:
        return ""
    if size < 1024:
        return "under 1 KB"
    if size < 1024 * 1024:
        return f"about {round(size / 1024)} KB"
    return f"about {size / (1024 * 1024):.1f} MB"


def item_heading(item):
    """A file's line in the window's list: its name and size."""
    size = size_text(item.size)
    return f"{item.name}  ({size})" if size else item.name


def sent_text(how, path):
    """What to say once the email is open: `how` is report_mail.OUTLOOK or MAIL_LINK."""
    if how == "outlook":
        return f"The report is attached to a new Outlook message. Press Send there. (It is also saved as {path}.)"
    return (f"Your email program is open with the message. Attach the report, {path}, before you send it "
            "(Explorer shows it).")
