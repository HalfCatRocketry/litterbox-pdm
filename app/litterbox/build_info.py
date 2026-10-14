"""
build_info.py - facts about where this build came from. The release pipeline REPLACES this file when it builds
the installer, so the values below are only what a development copy (running from the source files) sees.

    REPO         "owner/litterbox-pdm": the GitHub repository whose releases carry updates
    PUBLIC_KEY   the key (base64) that checks the signature on each release's latest.json

Left empty here on purpose: a development copy never offers to update itself.
"""

REPO = ""
PUBLIC_KEY = ""
