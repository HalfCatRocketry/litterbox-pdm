# PyInstaller hooks

Hooks in this folder replace PyInstaller's own hooks of the same name (see `hookspath` in `litterbox.spec`).

None are needed now. Before 0.4.0, Litterbox's modules sat at the top level, and its `workflow` module clashed
with a community hook for an unrelated PyPI package of the same name. Hooks match full module names, so the
modules inside the `litterbox` package (`litterbox.workflows.store`, ...) can't clash. Only a top-level name
could, and the only top-level names are `litterbox` and the start script `main.py`.
