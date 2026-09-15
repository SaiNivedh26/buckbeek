"""Code structure facts handed to the code-quality judgement agent, so its
tool budget goes on reading and judging code rather than on counting it."""

from __future__ import annotations

import posixpath
import re
import statistics

from pydantic import BaseModel

from gitcrawl.collectors.base import CollectorContext, CollectorResult, NoParams, collector
from gitcrawl.collectors.sources import (
    build_py_index,
    internal_imports,
    is_source_file,
    language,
    python_docstring_counts,
)

_MAX_FILES = 3000
_HASH_COMMENT = {"python", "ruby", "elixir"}
_SLASH_COMMENT = {
    "javascript",
    "typescript",
    "go",
    "rust",
    "java",
    "kotlin",
    "scala",
    "php",
    "csharp",
    "swift",
    "c",
    "cpp",
    "dart",
}
_SRC_ROOTS = ("src", "lib", "app", "pkg", "internal", "packages")


def _source_files(ctx: CollectorContext) -> list[str]:
    return [f for f in ctx.files.files() if is_source_file(f)][:_MAX_FILES]


# --- code.structure ------------------------------------------------------------------


class CodeStructureOutput(BaseModel):
    source_files: int
    source_lines: int
    languages: list[str]
    primary_language: str | None
    top_level_modules: list[str]
    max_file_lines: int
    median_file_lines: float | None
    files_over_500_lines: int
    files_over_1000_lines: int
    largest_files: list[str]
    comment_line_share: float | None
    python_docstring_share: float | None
    files_truncated_at_byte_cap: int


@collector(
    "code.structure",
    description=(
        "Source code shape (tests excluded): number of source files and lines, languages, top-level modules, "
        "largest files and how many exceed 500/1000 lines (god-file candidates), median file size, share of "
        "comment lines, and share of Python functions/classes with docstrings."
    ),
    category="code",
    output=CodeStructureOutput,
)
def code_structure(ctx: CollectorContext, params: NoParams) -> CollectorResult:
    sources = _source_files(ctx)
    sizes: dict[str, int] = {}
    lang_counts: dict[str, int] = {}
    comment_lines = code_lines = 0
    documented = definitions = 0
    truncated = 0

    for path in sources:
        text = ctx.files.read_text(path)
        if text is None:
            continue
        if len(text.encode("utf-8")) >= ctx.files.max_file_bytes:
            truncated += 1
        lang = language(path) or "other"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        lines = [ln.strip() for ln in text.splitlines()]
        non_empty = [ln for ln in lines if ln]
        sizes[path] = len(lines)
        code_lines += len(non_empty)
        if lang in _HASH_COMMENT:
            comment_lines += sum(1 for ln in non_empty if ln.startswith("#"))
        elif lang in _SLASH_COMMENT:
            comment_lines += sum(1 for ln in non_empty if ln.startswith(("//", "/*", "*")))
        if lang == "python":
            counts = python_docstring_counts(text)
            if counts:
                documented += counts[0]
                definitions += counts[1]

    modules: set[str] = set()
    for path in sources:
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] in _SRC_ROOTS:
            modules.add(f"{parts[0]}/{parts[1]}")
        elif len(parts) >= 2 and parts[0] not in _SRC_ROOTS:
            modules.add(parts[0])
    largest = sorted(sizes.items(), key=lambda kv: -kv[1])
    data = CodeStructureOutput(
        source_files=len(sources),
        source_lines=sum(sizes.values()),
        languages=[f"{lang}: {n} files" for lang, n in sorted(lang_counts.items(), key=lambda kv: -kv[1])],
        primary_language=max(lang_counts, key=lang_counts.get) if lang_counts else None,
        top_level_modules=sorted(modules)[:30],
        max_file_lines=largest[0][1] if largest else 0,
        median_file_lines=round(statistics.median(sizes.values()), 1) if sizes else None,
        files_over_500_lines=sum(1 for n in sizes.values() if n > 500),
        files_over_1000_lines=sum(1 for n in sizes.values() if n > 1000),
        largest_files=[f"{p} ({n} lines)" for p, n in largest[:10]],
        comment_line_share=round(comment_lines / code_lines, 3) if code_lines else None,
        python_docstring_share=round(documented / definitions, 3) if definitions else None,
        files_truncated_at_byte_cap=truncated,
    )
    return CollectorResult(data=data, citations=[p for p, _ in largest[:10]])


# --- code.imports ------------------------------------------------------------------------


class CodeImportsOutput(BaseModel):
    languages_analyzed: list[str]
    modules_analyzed: int
    internal_import_edges: int
    most_imported: list[str]
    highest_fan_out: list[str]
    import_cycle_count: int
    import_cycles: list[str]
    parse_failures: int


def _cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Strongly connected components with more than one member (Tarjan, iterative)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0
    for root in graph:
        if root in index:
            continue
        work = [(root, iter(graph.get(root, [])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(graph.get(child, []))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    result.append(sorted(component))
    return result


@collector(
    "code.imports",
    description=(
        "Internal import graph for Python and JavaScript/TypeScript source (tests excluded): most-imported "
        "modules (core abstractions / coupling hot spots), modules with the most internal imports, and "
        "import cycles between modules."
    ),
    category="code",
    output=CodeImportsOutput,
)
def code_imports(ctx: CollectorContext, params: NoParams) -> CollectorResult:
    sources = [s for s in _source_files(ctx) if language(s) in ("python", "javascript", "typescript")]
    file_set = set(sources)
    py_index = build_py_index(sorted((s for s in sources if s.endswith(".py")), key=len, reverse=True))
    graph: dict[str, list[str]] = {}
    failures = 0
    for path in sources:
        text = ctx.files.read_text(path)
        if text is None:
            continue
        targets = internal_imports(path, text, py_index, file_set)
        if targets is None:
            failures += 1
            continue
        graph[path] = targets

    fan_in: dict[str, int] = {}
    for targets in graph.values():
        for t in targets:
            fan_in[t] = fan_in.get(t, 0) + 1
    cycles = _cycles(graph)
    data = CodeImportsOutput(
        languages_analyzed=sorted({language(s) for s in sources}),
        modules_analyzed=len(graph),
        internal_import_edges=sum(len(t) for t in graph.values()),
        most_imported=[f"{p} (imported by {n})" for p, n in sorted(fan_in.items(), key=lambda kv: -kv[1])[:10]],
        highest_fan_out=[
            f"{p} (imports {len(t)})" for p, t in sorted(graph.items(), key=lambda kv: -len(kv[1]))[:5] if t
        ],
        import_cycle_count=len(cycles),
        import_cycles=[" <-> ".join(c[:6]) + (" …" if len(c) > 6 else "") for c in cycles[:5]],
        parse_failures=failures,
    )
    top = [re.sub(r" \(.*$", "", s) for s in data.most_imported[:5]]
    return CollectorResult(data=data, citations=top + [posixpath.normpath(c[0]) for c in cycles[:3]])
