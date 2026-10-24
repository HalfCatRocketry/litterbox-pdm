"""
bug_report_text.py - what Help > Report a problem says (the report itself is user/bug_report.py, sending it
user/report_mail.py): the window's words, and what to say once the email is open.
"""

PROMPT = "Briefly explain what you were doing at the time of the error"
NEEDS_COMMENT = "Please say briefly what you were doing, so the problem can be found."


def intro(address, problems):
    """The text at the top of the window. `problems` is how many problems the red status bar holds."""
    which = (f"The {problems} problem{'s' if problems != 1 else ''} in the red status bar go{'es' if problems == 1 else ''} "
             "in too.\n\n" if problems else "")
    return (f"This makes a report for the Litterbox team and opens an email to {address} with it, for you to send.\n\n"
            f"{which}"
            "The report has your comment, the versions of Litterbox, Windows, SolidWorks and Git, Litterbox's log, "
            "your Litterbox settings and this vault's shared settings. The log names parts and files you worked on. "
            "Passwords and tokens are taken out. You can open the report before you send it.")


def sent_text(how, path):
    """What to say once the email is open: `how` is report_mail.OUTLOOK or MAIL_LINK."""
    if how == "outlook":
        return f"The report is attached to a new Outlook message. Press Send there. (It is also saved as {path}.)"
    return (f"Your email program is open with the message. Attach the report, {path}, before you send it "
            "(Explorer shows it).")
