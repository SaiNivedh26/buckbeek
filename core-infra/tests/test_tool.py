import importlib.machinery
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest


TOOL_PATH = Path(__file__).parents[1] / "tool"
loader = importlib.machinery.SourceFileLoader("build_submit_tool", str(TOOL_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
tool = importlib.util.module_from_spec(spec)
loader.exec_module(tool)


class ArchiveTests(unittest.TestCase):
    def test_sensitive_and_generated_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')")
            (root / "qwik.json").write_text("secret")
            (root / "src" / "qwik.json").write_text("secret")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("secret")
            output = Path(directory) / "archive.tar.gz"
            count = tool.make_archive(root, output)
            self.assertEqual(count, 1)
            with tarfile.open(output, "r:gz") as archive:
                self.assertEqual(archive.getnames(), ["src/app.py"])

    def test_qwik_name_is_excluded_case_insensitively_on_client(self):
        self.assertTrue(tool.excluded("qwik.json"))
        self.assertTrue(tool.excluded("deep/qwik.json"))
        self.assertTrue(tool.excluded("deep/QWIK.JSON"))


if __name__ == "__main__":
    unittest.main()
