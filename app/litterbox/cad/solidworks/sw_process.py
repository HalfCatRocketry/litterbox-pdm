"""
sw_process.py - the SolidWorks program as a process: finding a SolidWorks Litterbox started, and making
sure it exits when Litterbox is done with it.
"""



def solidworks_installed():
    """Is SolidWorks installed on this computer (can Litterbox start it)? Looks for its program registration
    in the Windows registry; False on any other system."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID"):
            return True
    except Exception:
        return False


def installed_major_version():
    """The major version of the SolidWorks installed on this computer (32 for SolidWorks 2024), read from the
    Windows registry without starting it: the SldWorks.Application.N whose program is the one that starts.
    None if it isn't installed, or on any other system."""
    try:
        import winreg

        def clsid(name):
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name + r"\CLSID") as key:
                return winreg.QueryValue(key, None)

        current = clsid("SldWorks.Application")
    except Exception:
        return None
    for major in range(60, 9, -1):                          # newest first; a few old ones may still be listed
        try:
            if clsid(f"SldWorks.Application.{major}").lower() == current.lower():
                return major
        except OSError:
            continue
    return None


def solidworks_pids():
    """The process ids of every SLDWORKS.exe running now (empty if none, or on a system without tasklist)."""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return set()
    pids = set()
    for line in out.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) > 1 and parts[0].strip('"').lower() == "sldworks.exe" and parts[1].strip('"').isdigit():
            pids.add(int(parts[1].strip('"')))
    return pids


def own_process_id(sw, before):
    """The process id of a SolidWorks we just started: SolidWorks's own answer, or else the one that is new."""
    try:
        return int(sw.GetProcessID())
    except Exception:
        pass
    new = solidworks_pids() - set(before or ())
    return next(iter(new)) if len(new) == 1 else None


def process_is_running(pid):
    """Is this Windows process still running? (False on any other system.)"""
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False                                            # no such process any more
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    except Exception:
        return False


def end_process(pid):
    """Force a process to end."""
    import subprocess
    subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


EXIT_WAIT_SECONDS = 5.0       # how long a SolidWorks we started gets to exit by itself before we end it


def wait_for_exit(pid, timeout=EXIT_WAIT_SECONDS, alive=process_is_running, kill=end_process, sleep=None,
                  log=None):
    """Wait for a process to finish by itself; end it if it takes longer than `timeout` seconds.
    Returns "exited" or "ended"."""
    import time
    sleep = sleep or time.sleep
    waited = 0.0
    while alive(pid):
        if waited >= timeout:
            try:
                kill(pid)
            except Exception:
                pass
            if log:
                log(f"SolidWorks (process {pid}) did not exit by itself, so Litterbox ended it.")
            return "ended"
        sleep(0.25)
        waited += 0.25
    return "exited"
