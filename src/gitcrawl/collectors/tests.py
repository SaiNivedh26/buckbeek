"""Test analysis: what tests exist, which modules they reach, and what
coverage data or thresholds the repository declares.

The mapping is static (imports and file naming) — it answers "which modules
does any test touch", not "which lines run". Runtime coverage only comes
from committed coverage reports, and is reported separately.
"""

from __future__ import annotations

import json
import posixpath
import re
import tomllib

from pydantic import BaseModel

from gitcrawl.collectors.base import CollectorContext, CollectorResult, NoParams, collector
from gitcrawl.collectors.sources import (
    build_py_index,
    is_mappable_source,
    is_source_file,
    is_test_file,
    js_import_specs,
    kind_of_test,
    language,
    python_imports,
    resolve_js,
    resolve_py,
    subject_stem_of_test,
)

MAPPED_LANGUAGES = ("python", "javascript", "typescript", "go")
_NPM_DEFAULT_TEST = "no test specified"


# --- tests.inventory -------------------------------------------------------------


class TestInventoryOutput(BaseModel):
    test_file_count: int
    source_file_count: int
    test_to_source_ratio: float | None
    unit_test_files: int
    integration_test_files: int
    e2e_test_files: int
    frameworks: list[str]
    has_test_command: bool
    test_command: str | None
    test_directories: list[str]
    test_files: list[str]


def _json(text: str | None) -> dict:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _frameworks(ctx: CollectorContext, files: list[str], tests: list[str]) -> list[str]:
    read = ctx.files.read_text
    found: set[str] = set()

    pkg = _json(read("package.json"))
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    for dep, label in (
        ("jest", "jest"),
        ("vitest", "vitest"),
        ("mocha", "mocha"),
        ("ava", "ava"),
        ("jasmine", "jasmine"),
        ("karma", "karma"),
        ("@playwright/test", "playwright"),
        ("cypress", "cypress"),
        ("@testing-library/react", "testing-library"),
        ("supertest", "supertest"),
    ):
        if dep in deps:
            found.add(label)

    py_config = " ".join(filter(None, (read(f) for f in ("pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini"))))
    requirements = " ".join(filter(None, (read(f) for f in files if re.match(r"requirements[^/]*\.txt$", f))))
    if "pytest" in py_config or "pytest" in requirements or any(f.endswith("conftest.py") for f in files):
        found.add("pytest")
    for t in tests[:50]:
        if t.endswith(".py"):
            head = (read(t) or "")[:3000]
            if re.search(r"^\s*import pytest|^\s*from pytest", head, re.MULTILINE):
                found.add("pytest")
            if re.search(r"^\s*import unittest|^\s*from unittest", head, re.MULTILINE):
                found.add("unittest")

    if any(t.endswith("_test.go") for t in tests):
        found.add("go test")
    if any(t.endswith(".rs") for t in tests) or any(
        "#[test]" in (read(f) or "") for f in files[:400] if f.endswith(".rs")
    ):
        found.add("cargo test")
    if any(t.endswith("_spec.rb") for t in tests):
        found.add("rspec")
    jvm_build = " ".join(filter(None, (read(f) for f in ("pom.xml", "build.gradle", "build.gradle.kts"))))
    if "junit" in jvm_build.lower():
        found.add("junit")
    if "phpunit" in (read("composer.json") or "") or ctx.files.exists("phpunit.xml"):
        found.add("phpunit")
    return sorted(found)


def _test_command(ctx: CollectorContext) -> str | None:
    pkg = _json(ctx.files.read_text("package.json"))
    script = (pkg.get("scripts") or {}).get("test")
    if script and _NPM_DEFAULT_TEST not in script:
        return f"npm test ({script})"
    makefile = ctx.files.read_text("Makefile") or ""
    if re.search(r"^test\s*:", makefile, re.MULTILINE):
        return "make test"
    if ctx.files.exists("tox.ini"):
        return "tox"
    if ctx.files.exists("noxfile.py"):
        return "nox"
    return None


@collector(
    "tests.inventory",
    description=(
        "Test files and how they are organized: count of test files vs. source files, unit/integration/e2e "
        "split (by path), test frameworks detected from configs and imports, whether a test command is "
        "defined (package.json, Makefile, tox, nox), test directories, sample test files."
    ),
    category="tests",
    output=TestInventoryOutput,
)
def tests_inventory(ctx: CollectorContext, params: NoParams) -> CollectorResult:
    files = ctx.files.files()
    tests = [f for f in files if is_test_file(f)]
    sources = [f for f in files if is_source_file(f)]
    kinds = [kind_of_test(t) for t in tests]
    command = _test_command(ctx)
    dirs = sorted({posixpath.dirname(t) for t in tests if posixpath.dirname(t)})
    data = TestInventoryOutput(
        test_file_count=len(tests),
        source_file_count=len(sources),
        test_to_source_ratio=round(len(tests) / len(sources), 2) if sources else None,
        unit_test_files=kinds.count("unit"),
        integration_test_files=kinds.count("integration"),
        e2e_test_files=kinds.count("e2e"),
        frameworks=_frameworks(ctx, files, tests),
        has_test_command=command is not None,
        test_command=command,
        test_directories=dirs[:15],
        test_files=tests[:20],
    )
    return CollectorResult(data=data, citations=tests[:20])


# --- tests.mapping ------------------------------------------------------------------


class TestMappingOutput(BaseModel):
    method: str
    mapped_languages: list[str]
    unmapped_languages: list[str]
    source_modules: int
    tested_modules: int
    untested_modules: int
    tested_share: float | None
    untested_module_paths: list[str]
    tested_module_paths: list[str]


@collector(
    "tests.mapping",
    description=(
        "Which source modules any test reaches, by static analysis (Python imports, JS/TS import/require "
        "paths, Go package directories, and test file naming like test_x.py / x.test.ts): counts and share of "
        "tested vs. untested modules, largest untested modules first. Not runtime coverage."
    ),
    category="tests",
    output=TestMappingOutput,
)
def tests_mapping(ctx: CollectorContext, params: NoParams) -> CollectorResult:
    files = ctx.files.files()
    file_set = set(files)
    tests = [f for f in files if is_test_file(f)]
    sources = [f for f in files if is_mappable_source(f)]
    mappable = [s for s in sources if language(s) in MAPPED_LANGUAGES]
    unmapped_langs = sorted({language(s) for s in sources if language(s) not in MAPPED_LANGUAGES})
    py_index = build_py_index(sorted((s for s in mappable if s.endswith(".py")), key=len, reverse=True))

    tested: set[str] = set()
    by_stem: dict[str, list[str]] = {}
    for s in mappable:
        by_stem.setdefault(posixpath.basename(s).rsplit(".", 1)[0], []).append(s)

    for t in tests:
        lang = language(t)
        text = ctx.files.read_text(t) or ""
        if lang == "python":
            for name in python_imports(text, t) or []:
                hit = resolve_py(name, py_index)
                if hit:
                    tested.add(hit)
        elif lang in ("javascript", "typescript"):
            for spec in js_import_specs(text):
                hit = resolve_js(t, spec, file_set)
                if hit and hit in by_stem.get(posixpath.basename(hit).rsplit(".", 1)[0], []):
                    tested.add(hit)
        elif lang == "go":
            directory = posixpath.dirname(t)
            tested.update(s for s in mappable if s.endswith(".go") and posixpath.dirname(s) == directory)
        stem = subject_stem_of_test(t)
        if stem:
            tested.update(by_stem.get(stem, []))

    tested &= set(mappable)
    untested = [s for s in mappable if s not in tested]
    if len(untested) <= 500:
        untested.sort(key=lambda s: -ctx.files.line_count(s))
    data = TestMappingOutput(
        method="static: imports and test file naming, not runtime coverage",
        mapped_languages=sorted({language(s) for s in mappable}),
        unmapped_languages=unmapped_langs,
        source_modules=len(mappable),
        tested_modules=len(tested),
        untested_modules=len(untested),
        tested_share=round(len(tested) / len(mappable), 3) if mappable else None,
        untested_module_paths=untested[:30],
        tested_module_paths=sorted(tested)[:30],
    )
    return CollectorResult(data=data, citations=tests[:20])


# --- tests.coverage ---------------------------------------------------------------------


class CoverageOutput(BaseModel):
    report_files: list[str]
    line_coverage_percent: float | None
    coverage_source: str | None
    threshold_configured: bool
    threshold_percent: float | None
    threshold_source: str | None
    coverage_collected_in_ci: bool
    coverage_badge: bool
    badge_services: list[str]


def _report_coverage(ctx: CollectorContext, path: str) -> float | None:
    text = ctx.files.read_text(path) or ""
    lower = path.lower()
    if lower.endswith((".info", ".lcov")):
        found = sum(int(n) for n in re.findall(r"^LF:(\d+)", text, re.MULTILINE))
        hit = sum(int(n) for n in re.findall(r"^LH:(\d+)", text, re.MULTILINE))
        return round(100 * hit / found, 1) if found else None
    m = re.search(r"<coverage[^>]*\sline-rate=\"([\d.]+)\"", text)  # Cobertura (coverage.py, many tools)
    if m:
        return round(100 * float(m.group(1)), 1)
    counters = re.findall(
        r'<counter type="LINE" missed="(\d+)" covered="(\d+)"', text
    )  # JaCoCo, report level last
    if counters:
        missed, covered = map(int, counters[-1])
        return round(100 * covered / (missed + covered), 1) if missed + covered else None
    m = re.search(r'<metrics[^>]*\sstatements="(\d+)"[^>]*\scoveredstatements="(\d+)"', text)  # Clover
    if m and int(m.group(1)):
        return round(100 * int(m.group(2)) / int(m.group(1)), 1)
    return None


def _threshold(ctx: CollectorContext, files: list[str]) -> tuple[float | None, str | None]:
    read = ctx.files.read_text
    pyproject = read("pyproject.toml")
    if pyproject:
        try:
            value = (
                tomllib.loads(pyproject).get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
            )
        except tomllib.TOMLDecodeError:
            value = None
        if value is not None:
            return float(value), "pyproject.toml [tool.coverage.report] fail_under"
    for name in (".coveragerc", "setup.cfg", "tox.ini"):
        m = re.search(r"^\s*fail_under\s*=\s*([\d.]+)", read(name) or "", re.MULTILINE)
        if m:
            return float(m.group(1)), f"{name} fail_under"
    pkg = _json(read("package.json"))
    jest_global = ((pkg.get("jest") or {}).get("coverageThreshold") or {}).get("global") or {}
    for key in ("lines", "statements"):
        if key in jest_global:
            return float(jest_global[key]), "package.json jest.coverageThreshold"
    for f in files:
        base = posixpath.basename(f).lower()
        if re.match(r"(jest|vitest|vite)\.config\.[cm]?[jt]s$", base):
            text = read(f) or ""
            if re.search(r"coverageThreshold|thresholds", text):
                m = re.search(r"\b(?:lines|statements)\s*:\s*(\d+(?:\.\d+)?)", text)
                if m:
                    return float(m.group(1)), f"{f} coverage threshold"
    scripts = [read(f) or "" for f in files if f.lower().startswith(".github/workflows/")]
    scripts += [read("Makefile") or "", json.dumps(pkg.get("scripts") or {})]
    for text in scripts:
        m = re.search(r"--cov-fail-under[= ](\d+(?:\.\d+)?)", text)
        if m:
            return float(m.group(1)), "--cov-fail-under in CI/scripts"
    for name in ("codecov.yml", ".codecov.yml"):
        m = re.search(r"target:\s*(\d+(?:\.\d+)?)%?", read(name) or "")
        if m:
            return float(m.group(1)), f"{name} target"
    return None, None


@collector(
    "tests.coverage",
    description=(
        "Coverage evidence: committed coverage reports (lcov, Cobertura coverage.xml, JaCoCo, Clover) and the "
        "line coverage they show, configured coverage thresholds (coverage.py fail_under, --cov-fail-under, "
        "jest/vitest thresholds, codecov target), whether CI collects coverage, and coverage badges in the README."
    ),
    category="tests",
    output=CoverageOutput,
)
def tests_coverage(ctx: CollectorContext, params: NoParams) -> CollectorResult:
    from gitcrawl.collectors.ci import ci_config

    files = ctx.files.files()
    reports = [
        f
        for f in files
        if re.search(
            r"(^|/)(lcov\.info|[^/]+\.lcov|coverage\.xml|cobertura[^/]*\.xml|jacoco[^/]*\.xml|clover\.xml)$",
            f,
            re.IGNORECASE,
        )
    ]
    percent = source = None
    for r in reports:
        value = _report_coverage(ctx, r)
        if value is not None:
            percent, source = value, r
            break
    threshold, threshold_source = _threshold(ctx, files)

    if "ci.config" not in ctx.memo:
        ctx.memo["ci.config"] = ci_config(ctx, NoParams())
    ci = ctx.memo["ci.config"].data

    readme = next((f for f in ctx.files.inventory().root_files if f.lower().startswith("readme")), None)
    readme_text = ctx.files.read_text(readme) if readme else ""
    services = sorted(
        {
            name
            for name, pattern in (
                ("codecov", r"codecov\.io"),
                ("coveralls", r"coveralls\.io"),
                ("shields", r"img\.shields\.io/[^)\s]*coverage"),
                ("other", r"coverage[-_]?badge|badge[^)\s]*coverage"),
            )
            if re.search(pattern, readme_text or "", re.IGNORECASE)
        }
    )
    citations = reports + ([threshold_source.split(" ")[0]] if threshold_source else [])
    data = CoverageOutput(
        report_files=reports[:10],
        line_coverage_percent=percent,
        coverage_source=source,
        threshold_configured=threshold is not None,
        threshold_percent=threshold,
        threshold_source=threshold_source,
        coverage_collected_in_ci=ci.has_coverage_step,
        coverage_badge=bool(services),
        badge_services=services,
    )
    return CollectorResult(data=data, citations=citations)
