from pathlib import Path

from gitcrawl.collectors import CheckRequest, CollectorContext, RepoFiles, run_check
from gitcrawl.collectors.sources import is_source_file, is_test_file, py_module_names, subject_stem_of_test
from gitcrawl.config import get_config
from gitcrawl.source import local_handle

FIXTURES = Path(__file__).parent / "fixtures"


async def _data(root: Path, collector: str) -> dict:
    ctx = CollectorContext(handle=local_handle(root), cfg=get_config(), files=RepoFiles(root))
    fact = await run_check(CheckRequest("x", collector), ctx)
    assert fact.ok, fact.error
    return fact.data


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def test_file_classification():
    assert is_test_file("tests/test_calc.py") and is_test_file("src/a.spec.ts") and is_test_file("pkg/x_test.go")
    assert is_test_file("src/test/java/com/acme/CalcTest.java")
    assert not is_test_file("src/calc.py") and not is_test_file("README.md")
    assert is_source_file("src/calc.py")
    assert not is_source_file("vite.config.ts") and not is_source_file("docs/conf.py")
    assert py_module_names("src/pkg/mod.py") == ["src.pkg.mod", "pkg.mod"]
    assert py_module_names("src/calc.py") == ["src.calc", "calc"]
    assert subject_stem_of_test("tests/test_calc.py") == "calc" and subject_stem_of_test("a/b.test.ts") == "b"


async def test_tests_inventory_on_ci_rich():
    d = await _data(FIXTURES / "ci_rich", "tests.inventory")
    assert d["test_file_count"] == 1
    assert d["source_file_count"] == 3  # calc, payments, __init__
    assert d["frameworks"] == ["pytest"]
    assert d["unit_test_files"] == 1 and d["e2e_test_files"] == 0


async def test_tests_inventory_no_tests():
    d = await _data(FIXTURES / "no_tests", "tests.inventory")
    assert d["test_file_count"] == 0 and d["has_test_command"] is False


async def test_tests_mapping_finds_the_untested_module():
    d = await _data(FIXTURES / "ci_rich", "tests.mapping")
    assert d["tested_module_paths"] == ["src/calc.py"]
    assert d["untested_module_paths"] == ["src/payments.py"]
    assert d["tested_share"] == 0.5


async def test_tests_mapping_js_relative_imports_and_unmapped_languages(tmp_path):
    root = _write(
        tmp_path,
        {
            "src/cart.ts": "export const total = 1;\n",
            "src/checkout/index.ts": "export {}\n",
            "src/untested.ts": "export const x = 2;\n" * 10,
            "src/lib.rs": "pub fn f() {}\n",
            "tests/cart.spec.ts": "import { total } from '../src/cart';\nimport '../src/checkout';\n",
        },
    )
    d = await _data(root, "tests.mapping")
    assert set(d["tested_module_paths"]) == {"src/cart.ts", "src/checkout/index.ts"}
    assert d["untested_module_paths"] == ["src/untested.ts"]
    assert d["unmapped_languages"] == ["rust"]


async def test_tests_coverage_on_ci_rich():
    d = await _data(FIXTURES / "ci_rich", "tests.coverage")
    assert d["line_coverage_percent"] == 60.0 and d["coverage_source"] == "lcov.info"
    assert d["threshold_configured"] and d["threshold_percent"] == 80.0
    assert d["coverage_collected_in_ci"] is True
    assert d["coverage_badge"] is False


async def test_tests_coverage_jest_threshold_and_badge(tmp_path):
    root = _write(
        tmp_path,
        {
            "package.json": '{"jest": {"coverageThreshold": {"global": {"lines": 90}}}}',
            "README.md": "[![codecov](https://codecov.io/gh/a/b/badge.svg)](https://codecov.io/gh/a/b)",
            "coverage.xml": '<?xml version="1.0"?><coverage line-rate="0.834" branch-rate="0.5"></coverage>',
        },
    )
    d = await _data(root, "tests.coverage")
    assert d["threshold_percent"] == 90.0
    assert d["badge_services"] == ["codecov"]
    assert d["line_coverage_percent"] == 83.4


async def test_code_structure(tmp_path):
    big = '"""Module."""\n' + "".join(f"def f{i}():\n    return {i}\n" for i in range(600))
    root = _write(
        tmp_path,
        {
            "src/app/big.py": big,
            "src/app/small.py": 'class A:\n    """Doc."""\n\n# a comment\nx = 1\n',
            "tests/test_small.py": "def test():\n    pass\n",
        },
    )
    d = await _data(root, "code.structure")
    assert d["source_files"] == 2
    assert d["files_over_1000_lines"] == 1
    assert d["largest_files"][0].startswith("src/app/big.py")
    assert d["top_level_modules"] == ["src/app"]
    assert d["python_docstring_share"] == round(1 / 601, 3)


async def test_code_imports_fan_in_and_cycles(tmp_path):
    root = _write(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/core.py": "from pkg import util\n",
            "pkg/util.py": "from . import core\n",
            "pkg/api.py": "import pkg.core\nfrom pkg.util import helper\n",
            "web/a.ts": "import { b } from './b';\n",
            "web/b.ts": "import { a } from './a';\n",
        },
    )
    d = await _data(root, "code.imports")
    assert d["import_cycle_count"] == 2
    assert "pkg/core.py <-> pkg/util.py" in d["import_cycles"]
    assert d["most_imported"][0].startswith(("pkg/core.py", "pkg/util.py"))
    assert d["parse_failures"] == 0
