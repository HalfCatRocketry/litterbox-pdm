"""
House rules of the code (docs/ARCHITECTURE.md): small files, module names that nothing else hides, no reaching into
another module's private names, and package files that hold only a docstring.
"""

import ast
import unittest

from tests.architecture.code_index import APP, TESTS, bound_names, modules

MAX_LINES = 450


def line_count(path):
    return len(path.read_text(encoding="utf-8").splitlines())


class Conventions(unittest.TestCase):
    def test_no_program_file_is_too_long(self):
        long = sorted(f"{m.path.relative_to(APP)}: {line_count(m.path)}" for m in modules().values()
                      if line_count(m.path) > MAX_LINES)
        self.assertEqual(long, [], f"split files longer than {MAX_LINES} lines by job")

    def test_no_test_file_is_too_long(self):
        long = sorted(f"{p.relative_to(APP)}: {line_count(p)}" for p in TESTS.rglob("*.py")
                      if "__pycache__" not in p.parts and line_count(p) > MAX_LINES)
        self.assertEqual(long, [], f"split test files longer than {MAX_LINES} lines by what they test")

    def test_package_files_hold_only_a_docstring(self):
        wrong = []
        for m in modules().values():
            if m.path.name == "__init__.py":
                body = m.tree.body
                if not body or len(body) > 1 or not (isinstance(body[0], ast.Expr)
                                                     and isinstance(body[0].value, ast.Constant)):
                    wrong.append(m.name)
        self.assertEqual(sorted(wrong), [], "import each module from where it lives: no re-exports")

    def test_no_module_is_hidden_by_a_local_name(self):
        """A module imported as `runner` must not also be a variable or parameter called runner in the same file:
        inside that function, runner.run would then be the variable's, not the module's."""
        wrong = []
        for m in modules().values():
            bound = bound_names(m.tree)
            for imp in m.imports:
                if imp.is_module and imp.local in bound:
                    wrong.append(f"{m.name}: '{imp.local}' is a module and also a local name")
        self.assertEqual(sorted(set(wrong)), [])

    def test_no_reaching_into_another_modules_private_names(self):
        """Rule: shared means public. module._name from another file means _name should lose its underscore."""
        wrong = []
        for m in modules().values():
            locals_ = {imp.local for imp in m.imports if imp.is_module}
            for node in ast.walk(m.tree):
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in locals_
                        and node.attr.startswith("_") and not node.attr.startswith("__")):
                    wrong.append(f"{m.name} (line {node.lineno}): {node.value.id}.{node.attr}")
        self.assertEqual(sorted(set(wrong)), [])


if __name__ == "__main__":
    unittest.main()
