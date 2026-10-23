"""
toolbox_setting.py - after a refresh, once per vault and session: if the team keeps its own Toolbox (the Toolbox rule
TEAM, core/toolbox_rules.py) and this computer's SolidWorks uses another one, say so in the status line, before an
assembly with Toolbox parts from the wrong one is refused at Check In; and if it does use the team's, but some of its
files aren't downloaded yet (download on demand), say how to download them.
"""

from litterbox.cad import cad_programs
from litterbox.core import toolbox_rules
from litterbox.git import lfs_download
from litterbox.gui.logic import toolbox_text
from litterbox.vault import config
from litterbox.vault import toolbox_admin


class ToolboxSetting:
    """The Toolbox this computer's SolidWorks uses. One part of the main window (App)."""

    def _check_toolbox_setting(self):
        repo = self.repo()
        if not repo:
            return
        checked = self.__dict__.setdefault("_toolbox_setting_checked", set())
        if repo in checked:
            return
        checked.add(repo)
        try:
            if config.get_toolbox_rule(repo) != toolbox_rules.TEAM:
                return
            theirs = cad_programs.DEFAULT.library_folder()
        except Exception:                               # never let this get in the way of the parts list
            return
        team = str(toolbox_admin.folder_path(repo))
        if theirs and not toolbox_admin.same_folder(theirs, team):
            self._log("WARNING: " + toolbox_text.other_toolbox_warning(theirs, team))
            self._say(toolbox_text.other_toolbox_warning(theirs, team), "warn")
        elif theirs:
            try:
                missing = len(lfs_download.stubs(repo, toolbox_admin.tracked(repo)))
            except Exception:
                return
            if missing:
                self._say(toolbox_text.not_downloaded_warning(missing), "warn")
