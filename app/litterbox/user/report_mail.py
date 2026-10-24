"""
report_mail.py - handing a problem report (user/bug_report.py) to the person's email, ready to send: Litterbox has
no mail server of its own, so the person presses Send.

    how = report_mail.send(address, subject, body, attachment)     # OUTLOOK or MAIL_LINK

With Outlook (the classic, desktop one) installed, a new Outlook message opens with the zip attached, through
PowerShell (Outlook's COM interface; the values go in environment variables, so nothing in them is run). Otherwise
the default email program opens with the address, subject and text filled in (a mailto: link can't attach a file),
and Explorer shows the zip for the person to attach.
"""

import os
import subprocess
import urllib.parse

OUTLOOK, MAIL_LINK = "outlook", "mail_link"
MAX_LINK_BODY = 1500                # mailto: links longer than about 2000 characters are cut off by some programs

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_OUTLOOK_SCRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "$outlook = New-Object -ComObject Outlook.Application; "
    "$mail = $outlook.CreateItem(0); "
    "$mail.To = $env:LITTERBOX_MAIL_TO; "
    "$mail.Subject = $env:LITTERBOX_MAIL_SUBJECT; "
    "$mail.Body = $env:LITTERBOX_MAIL_BODY; "
    "[void]$mail.Attachments.Add($env:LITTERBOX_MAIL_FILE); "
    "$mail.Display()")


def has_outlook():
    """True if the classic (desktop) Outlook is installed: it registers Outlook.Application. False on any other
    system."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID"):
            return True
    except Exception:
        return False


def _outlook(address, subject, body, attachment):
    environment = dict(os.environ, LITTERBOX_MAIL_TO=address, LITTERBOX_MAIL_SUBJECT=subject,
                       LITTERBOX_MAIL_BODY=body, LITTERBOX_MAIL_FILE=str(attachment))
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _OUTLOOK_SCRIPT],
                            env=environment, capture_output=True, text=True, timeout=120, creationflags=_NO_WINDOW,
                            stdin=subprocess.DEVNULL)
    return result.returncode == 0


def mail_link(address, subject, body):
    """A mailto: link with the subject and text filled in (the text shortened to MAX_LINK_BODY characters)."""
    if len(body) > MAX_LINK_BODY:
        body = body[:MAX_LINK_BODY].rstrip() + "\n..."
    query = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{address}?{query}"


def send(address, subject, body, attachment):
    """Open a message to `address` for the person to send. Returns OUTLOOK if Outlook opened it with the zip
    attached, MAIL_LINK if the default email program was opened instead (the body asks them to attach the zip, and
    Explorer shows it)."""
    try:
        if has_outlook() and _outlook(address, subject, body, attachment):
            return OUTLOOK
    except (OSError, subprocess.SubprocessError):
        pass
    note = f"\n\nPlease attach the report: {attachment}"
    os.startfile(mail_link(address, subject, body[:MAX_LINK_BODY - len(note)] + note))
    subprocess.Popen(["explorer", "/select,", str(attachment)], creationflags=_NO_WINDOW)
    return MAIL_LINK
