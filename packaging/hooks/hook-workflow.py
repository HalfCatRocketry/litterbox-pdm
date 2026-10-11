# Litterbox has its own module called "workflow". PyInstaller's community hooks ship a hook with the same name for
# an unrelated package on PyPI, and that hook stops the build ("No package metadata was found for workflow").
# A hook with this name in our hooks folder is used instead of that one, and this one deliberately does nothing.
