"""Tests for sw_rename_test.py using a pretend SolidWorks. (The real Pack and Go can only be tried on Windows with
SolidWorks installed.) Run from tools/solidworks with the app folder on PYTHONPATH:  python -m unittest discover -s tests -v"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import sw_rename_test as rt
from test_sw_probe import FakeComponent, FakeModel, FakeSW


class TestBuildNewNames(unittest.TestCase):
    def test_top_is_number_one_and_drawings_share_their_models_number(self):
        j = os.path.join
        a, b, out = j(os.sep, "a"), j(os.sep, "b"), j(os.sep, "out")
        paths = [j(a, "Bolt.SLDPRT"), j(a, "Asm.SLDASM"), j(a, "Bolt.SLDDRW"), j(a, "Zed.SLDPRT"),
                 j(b, "Bolt.SLDPRT"), j(a, "Lonely.SLDDRW")]
        names = rt.build_new_names(paths, out, top=j(a, "Asm.SLDASM"))
        base = lambda p: os.path.basename(names[p])
        self.assertEqual(base(j(a, "Asm.SLDASM")), "TST-00001-001.SLDASM")
        self.assertEqual(base(j(a, "Bolt.SLDDRW"))[:-7], base(j(a, "Bolt.SLDPRT"))[:-7])
        self.assertTrue(base(j(a, "Bolt.SLDDRW")).endswith(".SLDDRW"))
        self.assertNotEqual(base(j(a, "Bolt.SLDPRT")), base(j(b, "Bolt.SLDPRT")))     # same name, other folder
        models = [base(p)[4:9] for p in paths if not p.endswith("DRW")]
        self.assertEqual(len(set(models)), 4)
        self.assertEqual(base(j(a, "Lonely.SLDDRW"))[4:9], "00005")                    # a drawing with no model

    def test_the_same_path_listed_twice_gets_one_name(self):
        names = rt.build_new_names([os.sep + "X.SLDPRT", os.sep + "X.SLDPRT"], os.sep + "out")
        self.assertEqual(len(names), 1)


class TestJudge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "new").mkdir()
        self.good = self.root / "new" / "TST-00002-001.SLDPRT"
        self.good.write_bytes(b"x")

    def judge(self, path, deps=()):
        comps = [{"name": "P-1", "path": str(path)}]
        return rt.judge(comps, list(deps), str(self.root / "src"), str(self.root / "new"), [str(self.good)])

    def test_a_correct_result_has_no_problems(self):
        self.assertEqual(self.judge(self.good, ["TST-00002-001", str(self.good)]), [])

    def test_component_pointing_back_at_the_original_is_flagged(self):
        original = self.root / "src" / "Part.SLDPRT"
        original.write_bytes(b"x")
        self.assertTrue(any("outside the new folder" in p for p in self.judge(original)))

    def test_missing_or_unrenamed_files_and_original_dependencies_are_flagged(self):
        self.assertTrue(any("does not exist" in p for p in self.judge(self.root / "new" / "TST-00009-001.SLDPRT")))
        plain = self.root / "new" / "Part.SLDPRT"
        plain.write_bytes(b"x")
        self.assertTrue(any("not one of the renamed" in p for p in self.judge(plain)))
        dep = str(self.root / "src" / "Part.SLDPRT")
        self.assertTrue(any("still depends on the ORIGINAL" in p for p in self.judge(self.good, ["Part", dep])))

    def test_expected_file_that_was_never_created(self):
        comps = []
        problems = rt.judge(comps, [], str(self.root / "src"), str(self.root / "new"), [str(self.root / "new" / "TST-00005-001.SLDPRT")])
        self.assertTrue(any("was not created" in p for p in problems))


class ExperimentCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.src, self.dest = root / "src", root / "out"
        self.src.mkdir()
        self.top = self.src / "Asm.SLDASM"
        self.top.write_bytes(b"asm")
        (self.src / "Bolt.SLDPRT").write_bytes(b"bolt")
        (self.src / "Bolt.SLDDRW").write_bytes(b"drw")

    def fake_pack(self, point_back=False, damage_original=False):
        def pack(model, dest, make_names, log):
            originals = [str(self.top), str(self.src / "Bolt.SLDPRT"), str(self.src / "Bolt.SLDDRW")]
            mapping = make_names(originals)
            os.makedirs(dest, exist_ok=True)
            for old, new in mapping.items():
                shutil.copyfile(old, new)
            if damage_original:
                (self.src / "Bolt.SLDPRT").write_bytes(b"CHANGED")
            return [0] * len(originals)
        return pack

    def opener(self, point_back=False):
        def open_func(sw, path):
            if os.path.dirname(path) == str(self.src):
                return FakeModel([]), 0, 0
            bolt = (self.src / "Bolt.SLDPRT") if point_back else next(self.dest.glob("*-001.SLDPRT"))
            return FakeModel([FakeComponent("Bolt-1", str(bolt)), FakeComponent("Bolt-2", str(bolt))]), 0, 0
        return open_func

    def run_it(self, pack=None, opener=None, sw=None):
        lines = []
        rt.experiment(str(self.top), str(self.dest), sw or FakeSW(FakeModel([])), open_func=opener or self.opener(),
                      pack_func=pack or self.fake_pack(), signatures=False, log=lines.append)
        return "\n".join(lines)


class TestExperiment(ExperimentCase):
    def test_a_good_run_passes_and_leaves_the_original_alone(self):
        sw = FakeSW(FakeModel([]))
        text = self.run_it(sw=sw)
        self.assertIn("Original folder check passed", text)
        self.assertIn("RESULT: PASSED", text)
        self.assertIn("Asm.SLDASM  ->  TST-00001-001.SLDASM", text)
        self.assertIn("distinct files they point at: 1", text)
        self.assertEqual(len(sw.closed), 2)                          # both models closed; the fake raises on any save

    def test_the_original_need_not_be_opened(self):
        sw = FakeSW(FakeModel([]))
        calls = []

        def opener(sw_, path):
            calls.append(path)
            return self.opener()(sw_, path)

        lines = []
        rt.experiment(str(self.top), str(self.dest), sw, open_func=opener, signatures=False, open_original=False,
                      pack_func=lambda model, dest, make_names, log: self.fake_pack()(model, dest, make_names, log),
                      log=lines.append)
        text = "\n".join(lines)
        self.assertIn("RESULT: PASSED", text)
        self.assertEqual(len(calls), 1)                              # only the NEW assembly was opened

    def test_references_that_still_point_at_the_original_fail(self):
        text = self.run_it(opener=self.opener(point_back=True))
        self.assertIn("RESULT: PROBLEMS FOUND", text)
        self.assertIn("outside the new folder", text)

    def test_a_changed_original_fails(self):
        text = self.run_it(pack=self.fake_pack(damage_original=True))
        self.assertIn("ORIGINAL FOLDER CHECK FAILED", text)
        self.assertIn("modified: Bolt.SLDPRT", text)
        self.assertIn("RESULT: PROBLEMS FOUND", text)

    def test_pack_and_go_exception_is_reported_not_a_crash(self):
        def boom(model, dest, make_names, log):
            raise RuntimeError("COM error")
        text = self.run_it(pack=boom)
        self.assertIn("Pack and Go failed", text)
        self.assertIn("RESULT: PROBLEMS FOUND", text)
        self.assertIn("Original folder check passed", text)

    def test_refuses_a_destination_that_is_not_empty_or_overlaps(self):
        self.dest.mkdir()
        (self.dest / "old.txt").write_text("x")
        self.assertIn("not empty", self.run_it())
        lines = []
        rt.experiment(str(self.top), str(self.src / "inner"), FakeSW(FakeModel([])), open_func=self.opener(),
                      pack_func=self.fake_pack(), signatures=False, log=lines.append)
        self.assertIn("overlap", "\n".join(lines))
        self.assertEqual(sorted(p.name for p in self.src.iterdir()), ["Asm.SLDASM", "Bolt.SLDDRW", "Bolt.SLDPRT"])


class TestAudit(ExperimentCase):
    def test_audit_reports_references_outside_the_folder_and_changes_nothing(self):
        (self.dest).mkdir()
        new_top = self.dest / "TST-00001-001.SLDASM"
        new_top.write_bytes(b"asm")
        inside = self.dest / "TST-00002-001.SLDPRT"
        inside.write_bytes(b"p")
        model = FakeModel([FakeComponent("Bolt-1", str(inside)), FakeComponent("Nut-1", str(self.src / "Nut.SLDPRT"))])
        lines = []
        rt.audit(str(new_top), FakeSW(model), open_func=lambda sw, p: (model, 0, 0), log=lines.append)
        text = "\n".join(lines)
        self.assertIn("Auditing 2 CAD file(s)", text)
        self.assertIn("2 component(s), all levels; 1 resolve to a file outside the folder", text)
        self.assertIn("Nut-1", text)
        self.assertIn("1 of them load a renamed file", text)
        self.assertIn("Nothing in the folder changed.", text)


class TestHelpers(unittest.TestCase):
    def test_get_member_reads_properties_methods_and_returns_com_objects_untouched(self):
        class Com:
            _oleobj_ = object()
            def __call__(self):
                raise AssertionError("a COM object must not be called")
        class Thing:
            Prop = 5
            child = Com()
            def Method(self):
                return 7
        t = Thing()
        self.assertEqual(rt.get_member(t, "Prop"), 5)
        self.assertEqual(rt.get_member(t, "Method"), 7)
        self.assertIs(rt.get_member(t, "child"), t.child)

    def test_describe_enum_lists_names_and_values(self):
        class Var:
            def __init__(self, memid, value):
                self.memid, self.value = memid, value

        class Info:
            def GetTypeAttr(self):
                return type("A", (), {"cVars": 2})()
            def GetVarDesc(self, k):
                return Var(k, k * 2)
            def GetNames(self, memid):
                return [("swNone", "swOverwrite")[memid]]

        class Lib:
            def GetTypeInfoCount(self):
                return 1
            def GetDocumentation(self, i):
                return "swMoveCopyOption_e", "", 0, ""
            def GetTypeInfo(self, i):
                return Info()

        self.assertEqual(rt.describe_enum(Lib(), "swMoveCopyOption_e"),
                         ["swMoveCopyOption_e: swNone = 0", "swMoveCopyOption_e: swOverwrite = 2"])
        self.assertIn("not found", rt.describe_enum(Lib(), "other")[0])
        self.assertIn("could not read", rt.describe_enum(object(), "x")[0])

    def test_new_name_for_matches_stale_folders_by_file_name(self):
        j = os.path.join
        mapping = {j(os.sep, "R01", "Bolt.SLDPRT"): "new1", j(os.sep, "R01", "Nut.SLDPRT"): "new2",
                   j(os.sep, "R01", "sub", "Nut.sldprt"): "new3"}
        self.assertEqual(rt.new_name_for(j(os.sep, "R01", "Bolt.SLDPRT"), mapping), "new1")
        self.assertEqual(rt.new_name_for(j(os.sep, "R01 FIXED", "BOLT.sldprt"), mapping), "new1")
        self.assertIsNone(rt.new_name_for(j(os.sep, "R01 FIXED", "Nut.SLDPRT"), mapping))      # two files share the name
        self.assertIsNone(rt.new_name_for(j(os.sep, "R01 FIXED", "Washer.SLDPRT"), mapping))

    def test_sibling_drawing_is_found_by_name_and_folder(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("Bolt.SLDPRT", "BOLT.slddrw", "Nut.SLDPRT", "Other.SLDDRW"):
                Path(d, name).write_bytes(b"x")
            self.assertEqual(os.path.basename(rt.sibling_drawing(os.path.join(d, "Bolt.SLDPRT"))), "BOLT.slddrw")
            self.assertIsNone(rt.sibling_drawing(os.path.join(d, "Nut.SLDPRT")))
            self.assertIsNone(rt.sibling_drawing(os.path.join(d, "nope", "X.SLDPRT")))

    def test_copy_order_puts_children_first_once_each(self):
        tree = {"top": ["a", "b"], "a": ["c"], "b": ["c"], "c": []}
        order = rt.copy_order("top", lambda p: tree[p])
        self.assertEqual(order, ["c", "a", "b", "top"])
        self.assertEqual(rt.copy_order("top", lambda p: {"top": ["A", "a"], "A": [], "a": []}[p]).count("top"), 1)

    def test_copy_order_refuses_a_loop(self):
        with self.assertRaises(ValueError):
            rt.copy_order("a", lambda p: {"a": ["b"], "b": ["a"]}[p])

    def test_describe_interface_lists_parameters_with_their_directions(self):
        class Desc:
            def __init__(self, memid, args, invkind):
                self.memid, self.args, self.invkind = memid, args, invkind

        class Info:
            funcs = [Desc(1, [(None, 1, None), (None, 2, None)], 1), Desc(2, [], 2)]
            names = {1: ["SetSaveToName", "SaveToName", "Name"], 2: ["Other"]}
            def GetTypeAttr(self):
                return type("A", (), {"cFuncs": 2})()
            def GetFuncDesc(self, k):
                return self.funcs[k]
            def GetNames(self, memid):
                return self.names[memid]

        class Lib:
            def GetTypeInfoCount(self):
                return 2
            def GetDocumentation(self, i):
                return ("IOther", "IPackAndGo")[i], "", 0, ""
            def GetTypeInfo(self, i):
                return Info()

        self.assertEqual(rt.describe_interface(Lib(), "IPackAndGo"),
                         ["IPackAndGo.SetSaveToName(SaveToName[in], Name[out]) [method]", "IPackAndGo.Other() [get]"])
        self.assertEqual(rt.describe_interface(Lib(), "IPackAndGo", ("save",)),
                         ["IPackAndGo.SetSaveToName(SaveToName[in], Name[out]) [method]"])
        self.assertIn("nothing found", rt.describe_interface(Lib(), "IMissing")[0])
        self.assertIn("could not read", rt.describe_interface(object(), "IPackAndGo")[0])

    def test_load_typelib_failure_is_reported_not_raised(self):
        self.assertIsNone(rt.load_typelib(object()))
        lines = []
        rt.experiment(r"X:\none\a.SLDASM", r"Y:\none\out", FakeSW(FakeModel([])), open_func=lambda s, p: (None, 1, 0),
                      pack_func=lambda *a: [], log=lines.append)

    def test_is_inside(self):
        j = os.path.join
        root = j(os.sep, "A")
        self.assertTrue(rt.is_inside(j(root, "b", "c.txt"), root))
        self.assertFalse(rt.is_inside(j(os.sep, "AB", "c.txt"), root))
        self.assertFalse(rt.is_inside(None, root))


if __name__ == "__main__":
    unittest.main()