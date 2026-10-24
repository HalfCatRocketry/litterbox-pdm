"""
home_data.py - what Home needs from the vault, read with each refresh (in the background): the Team and project
folders (folders/folder_store.py), the org's projects, and the ECOs' titles (for ECOs in folders). Nothing here may
stop the parts list from showing: a part that can't be read is left out and logged.

    trees, projects, eco_titles = home_data.load(repo)
"""

from litterbox import diagnostics
from litterbox.change_orders import eco_store
from litterbox.folders import folder_store
from litterbox.vault import config


def load(repo):
    try:
        trees = folder_store.load(repo)
    except Exception as e:
        diagnostics.LOG(f"WARNING: the folders couldn't be read: {e}")
        trees = folder_store.Trees()
    try:
        projects = config.get_projects(repo)
    except Exception as e:
        diagnostics.LOG(f"WARNING: the projects couldn't be read for the folders: {e}")
        projects = []
    try:
        ecos, _problems = eco_store.load_all(repo)
        titles = {eco.number: eco.name for eco in ecos}
    except Exception:
        titles = {}
    return trees, projects, titles
