"""Shared, language-aware helpers for the test and code collectors: which
files are source vs. tests, and static import extraction/resolution for
Python (ast) and JavaScript/TypeScript (import/require specifiers).

Static analysis only — "tested" below means "a test imports it or is named
after it", never runtime coverage. The collectors say so in their output.
"""

from __future__ import annotations

import ast
import posixpath
import re

LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "javascript",
    ".svelte": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".scala": "scala",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
}
JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")

_TEST_DIR_RE = re.compile(r"(^|/)(tests?|__tests__|specs?|e2e|cypress|integration[-_]?tests?)/", re.IGNORECASE)
_TEST_NAME_RE = re.compile(
    r"(^|/)(test_[^/]+|[^/]+_test|[^/]+\.(test|spec)|[^/]+_spec)\.[a-z0-9]+$", re.IGNORECASE
)
_JVM_TEST_RE = re.compile(r"(^|/)[A-Z]\w*(Test|Tests|IT|Spec)\.(java|kt|scala|cs|swift)$")
_NON_SOURCE_RE = re.compile(
    r"(^|/)(docs?|examples?|samples?|demos?|scripts?|migrations?|benchmarks?|fixtures?|vendor|third_party"
    r"|\.github)/",
    re.IGNORECASE,
)
_CONFIG_NAME_RE = re.compile(
    r"(^|/)([^/]+\.config\.[a-z]+|setup\.py|conftest\.py|manage\.py|[^/]+\.d\.ts|gulpfile\.js|gruntfile\.js)$",
    re.IGNORECASE,
)
_E2E_RE = re.compile(r"e2e|end[-_]to[-_]end|cypress|playwright|selenium", re.IGNORECASE)
_INTEGRATION_RE = re.compile(r"integration|functional|acceptance|contract", re.IGNORECASE)

JS_IMPORT_RE = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s+)['"]([^'"\n]+)['"]""", re.MULTILINE
)


def language(path: str) -> str | None:
    dot = path.rfind(".")
    return LANGUAGES.get(path[dot:].lower()) if dot != -1 else None


def is_test_file(path: str) -> bool:
    if language(path) is None:
        return False
    return bool(_TEST_DIR_RE.search(path) or _TEST_NAME_RE.search(path) or _JVM_TEST_RE.search(path))


def is_source_file(path: str) -> bool:
    return (
        language(path) is not None
        and not is_test_file(path)
        and not _NON_SOURCE_RE.search(path)
        and not _CONFIG_NAME_RE.search(path)
    )


def is_mappable_source(path: str) -> bool:
    return is_source_file(path) and posixpath.basename(path) not in ("__init__.py", "__main__.py")


def kind_of_test(path: str) -> str:
    if _E2E_RE.search(path):
        return "e2e"
    if _INTEGRATION_RE.search(path):
        return "integration"
    return "unit"


def subject_stem_of_test(path: str) -> str | None:
    """ "test_calc.py" / "calc_test.go" / "calc.spec.ts" -> "calc"."""
    name = posixpath.basename(path)
    stem = name.rsplit(".", 1)[0]
    for pattern in (
        r"^test_(.+)$",
        r"^(.+)_test$",
        r"^(.+)\.(?:test|spec)$",
        r"^(.+)_spec$",
        r"^(.+?)(?:Tests?|IT)$",
    ):
        m = re.match(pattern, stem)
        if m:
            return m.group(1)
    return None


# --- Python ------------------------------------------------------------------


def py_module_names(path: str) -> list[str]:
    """Dotted names a Python file can be imported as: the full path, every
    suffix of 2+ segments, and the bare name for top-level or src/-layout files."""
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return []
    names = []
    for i in range(len(parts)):
        suffix = parts[i:]
        if len(suffix) >= 2 or len(parts) == 1 or (i == 1 and parts[0] in ("src", "lib", "app", "python")):
            names.append(".".join(suffix))
    return names


def build_py_index(paths: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    # Longer (more specific) names first so they win any collision.
    for path in paths:
        for name in py_module_names(path):
            index.setdefault(name, path)
    return index


def python_imports(text: str, path: str) -> list[str] | None:
    """Absolute dotted names imported by a Python file (relative imports
    resolved), or None if the file doesn't parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    package = path.split("/")[:-1]
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                up = node.level - 1
                base = package[: len(package) - up] if up <= len(package) else []
                module = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                module = node.module or ""
            if module:
                names.append(module)
            names.extend(f"{module}.{a.name}" if module else a.name for a in node.names if a.name != "*")
    return names


def resolve_py(name: str, index: dict[str, str]) -> str | None:
    parts = name.split(".")
    for k in range(len(parts), 0, -1):
        hit = index.get(".".join(parts[:k]))
        if hit:
            return hit
    return None


def python_docstring_counts(text: str) -> tuple[int, int] | None:
    """(definitions with a docstring, total functions+classes), or None if unparseable."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    documented = sum(1 for n in defs if ast.get_docstring(n))
    return documented, len(defs)


# --- JavaScript / TypeScript ---------------------------------------------------


def js_import_specs(text: str) -> list[str]:
    return JS_IMPORT_RE.findall(text)


def resolve_js(from_path: str, spec: str, file_set: set[str]) -> str | None:
    if spec.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(from_path), spec))
    elif spec.startswith(("@/", "~/")):
        base = "src/" + spec[2:]
    else:
        return None  # a package, not a repo file
    if base.startswith(".."):
        return None
    candidates = [base, *(base + e for e in JS_EXTS), *(f"{base}/index{e}" for e in JS_EXTS)]
    if base.endswith((".js", ".jsx", ".mjs")):
        stem = base.rsplit(".", 1)[0]
        candidates += [stem + ".ts", stem + ".tsx"]
    for candidate in candidates:
        if candidate in file_set:
            return candidate
    return None


def internal_imports(path: str, text: str, py_index: dict[str, str], file_set: set[str]) -> list[str] | None:
    """Repo files imported by `path`, or None if it couldn't be parsed."""
    lang = language(path)
    targets: list[str] = []
    if lang == "python":
        names = python_imports(text, path)
        if names is None:
            return None
        for name in names:
            hit = resolve_py(name, py_index)
            if hit and hit != path:
                targets.append(hit)
    elif lang in ("javascript", "typescript"):
        for spec in js_import_specs(text):
            hit = resolve_js(path, spec, file_set)
            if hit and hit != path:
                targets.append(hit)
    return list(dict.fromkeys(targets))
