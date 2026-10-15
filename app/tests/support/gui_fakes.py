"""Stand-ins for tkinter and customtkinter, and the loader that builds the window's modules on them, so window tests run anywhere without opening a window. No tests here.

load_gui_with_fakes(box) imports every window module afresh under the fakes and returns a namespace of them (gui.app.App, gui.request_dialog, ...) plus every module they use (gui.lifecycle, gui.messagebox, ...)."""

import importlib
import sys
import types
from unittest import mock
from tests.support.gui_source import GUI_DIR
from litterbox.importing import session as import_session


REAL_SESSION = import_session.ImportSession


class Anything:
    """A widget that accepts any call and remembers nothing."""

    def __init__(self, *args, **kwargs):
        self.options = dict(kwargs)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return mock.MagicMock()

    def configure(self, *args, **kwargs):
        self.options.update(kwargs)

    def cget(self, key):
        return self.options.get(key)


class FakeVar:
    def __init__(self, value=None, **kwargs):
        self.value, self.watchers = value, []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for watcher in self.watchers:
            watcher("", "", "write")

    def trace_add(self, mode, callback):
        self.watchers.append(callback)


class FakeTree(Anything):
    def __init__(self, parent=None, columns=(), **kwargs):
        super().__init__()
        self.columns, self.rows, self.chosen = list(columns), {}, ()

    def insert(self, parent, index, iid=None, tags=(), values=()):
        self.rows[iid] = {"tags": tags, "values": list(values)}

    def get_children(self):
        return tuple(self.rows)

    def delete(self, *ids):
        for i in ids:
            self.rows.pop(i, None)

    def exists(self, iid):
        return iid in self.rows

    def item(self, iid, option=None, **changes):
        if "tags" in changes:
            self.rows[iid]["tags"] = changes["tags"]
        return tuple(self.rows[iid]["tags"]) if option == "tags" else None

    def selection(self):
        return self.chosen

    def selection_set(self, *ids):
        self.chosen = ids

    def set(self, iid, column, value=None):
        if value is not None:
            self.rows[iid]["values"][self.columns.index(column)] = value
        return self.rows[iid]["values"][self.columns.index(column)]


class FakeBox:
    def __init__(self):
        self.calls = []
        self.answer = True              # what Yes/No questions are answered with

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a, k))
            return self.answer if name in ("askyesno", "askokcancel") else None
        return call


def fake_jobs(busy=False, pending=None):
    """Stands in for the window's job queue in tests that build the window without running its __init__."""
    return types.SimpleNamespace(active=lambda: busy, working=lambda: busy, pending_parts=lambda: dict(pending or {}))


def load_gui_with_fakes(box):
    ctk = types.ModuleType("customtkinter")
    ctk.__getattr__ = lambda name: Anything
    tk = types.ModuleType("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    tk.StringVar = tk.BooleanVar = FakeVar
    tk.__getattr__ = lambda name: Anything
    ttk = types.ModuleType("tkinter.ttk")
    ttk.Treeview = FakeTree
    ttk.Style = Anything
    dialogs = types.ModuleType("tkinter.filedialog")
    dialogs.askdirectory = lambda **k: ""
    dialogs.askopenfilename = lambda **k: ""
    mbox = types.ModuleType("tkinter.messagebox")
    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
        setattr(mbox, name, getattr(box, name))
    tk.filedialog, tk.messagebox, tk.ttk = dialogs, mbox, ttk
    fakes = {"customtkinter": ctk, "tkinter": tk, "tkinter.ttk": ttk, "tkinter.filedialog": dialogs,
             "tkinter.messagebox": mbox}
    with mock.patch.dict(sys.modules, fakes):
        # Every window module is imported afresh, under the fakes (patch.dict puts sys.modules back afterwards).
        for name in [n for n in sys.modules if n.startswith("litterbox.gui.")]:
            if not n_is_logic(name):
                del sys.modules[name]
        modules = {}
        for path in sorted(GUI_DIR.rglob("*.py")):
            rel = path.relative_to(GUI_DIR.parents[1]).with_suffix("")
            dotted = ".".join(rel.parts).removesuffix(".__init__")
            if not n_is_logic(dotted):
                modules[dotted] = importlib.import_module(dotted)
    # self.gui.<module> is each window module, and every module those use (self.gui.lifecycle, .messagebox, ...)
    gui = types.SimpleNamespace()
    for module in modules.values():
        for name, value in vars(module).items():
            if isinstance(value, types.ModuleType) and not hasattr(gui, name):
                setattr(gui, name, value)
    for dotted, module in modules.items():
        setattr(gui, dotted.rsplit(".", 1)[1], module)
    return gui


def n_is_logic(dotted):
    """gui/logic has no window code: it is not reloaded."""
    return dotted == "litterbox.gui.logic" or dotted.startswith("litterbox.gui.logic.")


def replace(test, obj, name, value):
    """Swap an attribute for this one test only. The program's modules are shared by every test in a run, so a
    swap that isn't undone would break whichever test runs next."""
    original = getattr(obj, name)
    test.addCleanup(setattr, obj, name, original)
    setattr(obj, name, value)


class FakeParent:
    def winfo_rootx(self): return 0
    def winfo_rooty(self): return 0
    def winfo_width(self): return 1200
    def winfo_height(self): return 800


class FakeWindow:
    """Just enough of a window to watch the fade: it records opacity changes and queued timers."""

    def __init__(self):
        self.alpha, self.alphas, self.timers, self.destroyed = 1.0, [], [], False

    def attributes(self, name, value):
        self.alpha = value
        self.alphas.append(value)

    def after(self, ms, fn):
        self.timers.append(fn)

    def bind(self, *args, **kwargs):
        pass

    def winfo_exists(self):
        return not self.destroyed

    def protocol(self, name, handler):
        self.protocols = getattr(self, "protocols", {})
        self.protocols[name] = handler

    def iconbitmap(self, *args, **kwargs):
        self.icon_calls = getattr(self, "icon_calls", 0) + 1

    def destroy(self):
        self.destroyed = True

    def run_timers(self):
        while self.timers and not self.destroyed:
            self.timers.pop(0)()


class SortableFakeTree(FakeTree):
    def __init__(self, columns):
        super().__init__(None, columns)
        self.titles, self.commands = {}, {}

    def heading(self, column, text=None, command=None, **kwargs):
        if text is not None:
            self.titles[column] = text
        if command is not None:
            self.commands[column] = command

    def move(self, iid, parent, position):
        order = [i for i in self.rows if i != iid]
        order.insert(position, iid)
        self.rows = {i: self.rows[i] for i in order}
