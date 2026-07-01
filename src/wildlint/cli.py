"""Command-line entry point for wildlint."""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import sys
import tokenize
from io import StringIO
from pathlib import Path

from .checkers import CHECKERS, Finding, check_source
from .property_templates import TEMPLATES, get_template

# Junk directories never worth scanning when walking a tree. Matched against
# path *components below the walked root* (so `wildlint .venv` still honours an
# explicit arg), not against explicit file arguments.
_DEFAULT_EXCLUDE_DIRS = frozenset(
    {
        ".venv",
        ".virtualenv",
        "venv",
        ".tox",
        "node_modules",
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".benchmarks",
        "build",
        "dist",
        ".eggs",
        ".idea",
        ".vscode",
        "site-packages",
    }
)

_CONFIG_KEYS = {"select", "pedantic", "exclude"}


def _is_excluded(
    path: Path,
    *,
    no_default_exclude: bool,
    extra_excludes,
    skip_first: int = 0,
) -> bool:
    """Should a rglob-discovered `path` be skipped?

    Default-excludes match directory components *below* the walked root
    (`skip_first` drops the root's own parts, so pointing wildlint at a junk dir
    directly still scans it). `extra_excludes` are user/config globs matched
    against the full path string.
    """
    sub_parts = path.parts[skip_first:]
    if not no_default_exclude and any(p in _DEFAULT_EXCLUDE_DIRS for p in sub_parts):
        return True
    if extra_excludes:
        full = str(path)
        rel = Path(*sub_parts).as_posix() if sub_parts else ""
        for pat in extra_excludes:
            if (
                fnmatch.fnmatch(full, pat)
                or (rel and fnmatch.fnmatch(rel, pat))
                or any(fnmatch.fnmatch(part, pat) for part in sub_parts)
            ):
                return True
    return False


def _iter_python_files(paths, *, no_default_exclude=False, extra_excludes=()):
    """Yield `.py` files to lint. Explicit file args are scanned as-is; directory
    args are walked with default/config excludes applied to descendants."""
    for raw in paths:
        root = Path(raw)
        if root.is_dir():
            skip = len(root.parts)
            for f in sorted(root.rglob("*.py")):
                if not _is_excluded(
                    f,
                    no_default_exclude=no_default_exclude,
                    extra_excludes=extra_excludes,
                    skip_first=skip,
                ):
                    yield f
        elif root.is_file() and root.suffix == ".py":
            yield root


def _parse_noqa(source: str) -> dict[int, set[str] | None]:
    """Line number -> suppressed codes (``None`` = bare ``# noqa``, all codes).

    Uses ``tokenize`` so a noqa comment inside a string literal does not falsely
    suppress -- the same respect-lexical-structure lesson as WL005's paren peek.
    Returns an empty dict if the source did not tokenize cleanly.
    """
    out: dict[int, set[str] | None] = {}
    try:
        for tok in tokenize.generate_tokens(StringIO(source).readline):
            if tok.type != tokenize.COMMENT:
                continue
            payload = tok.string.strip().lstrip("#").strip()
            low = payload.lower()
            lineno = tok.start[0]
            if low == "noqa":
                out[lineno] = None  # suppress every code on this line
            elif low.startswith("noqa:"):
                codes = {c.strip().upper() for c in payload[5:].split(",") if c.strip()}
                current = out.get(lineno)
                if current is None and lineno in out:
                    continue  # a bare noqa already suppresses everything
                out[lineno] = (current | codes) if current is not None else codes
    except tokenize.TokenError:
        return {}
    return out


def check_file(
    path: Path, *, pedantic: bool = False, codes: set[str] | None = None
) -> tuple[list[Finding], list[str]]:
    """Return ``(findings, errors)`` for one file.

    Findings are noqa-filtered. Errors are diagnostic strings (syntax/decode/
    unreadable) -- they are *not* findings and surface on stderr in text mode.
    """
    errors: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], [f"{path}: error: not valid UTF-8, skipped"]
    except OSError as exc:
        return [], [f"{path}: error: {exc.strerror or exc}"]

    try:
        findings = check_source(source, str(path), pedantic=pedantic, codes=codes)
    except SyntaxError as exc:
        loc = f"{path}:{exc.lineno}:{exc.offset}: " if exc.lineno else f"{path}: "
        return [], [f"{loc}SyntaxError: {exc.msg}"]

    noqa = _parse_noqa(source)
    if noqa:
        kept: list[Finding] = []
        for f in findings:
            if f.line in noqa:
                directive = noqa[f.line]
                if directive is None or f.code.upper() in directive:
                    continue  # bare noqa (all codes) or matching code -> suppress
            kept.append(f)
        findings = kept
    return findings, errors


def _load_config(cwd: Path) -> dict:
    """Read ``[tool.wildlint]`` from the nearest ``pyproject.toml`` at/above cwd.

    Recognized keys: ``select`` (list[str]), ``pedantic`` (bool), ``exclude``
    (list[str] globs). Unknown keys warn on stderr but do not crash. Returns
    ``{}`` when there is no table or no parser (Python <3.11 without ``tomli``).
    """
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            tomllib = None  # type: ignore[assignment]

    candidate: Path | None = None
    for dirpath in (cwd, *cwd.parents):
        if (dirpath / "pyproject.toml").is_file():
            candidate = dirpath / "pyproject.toml"
            break
    if candidate is None or "[tool.wildlint]" not in candidate.read_text(
        encoding="utf-8"
    ):
        return {}

    if tomllib is None:
        print(
            f"{candidate}: [tool.wildlint] present but no TOML parser available "
            "(need Python 3.11+ or the 'tomli' package); config ignored",
            file=sys.stderr,
        )
        return {}
    try:
        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        print(f"{candidate}: invalid TOML ({exc}); config ignored", file=sys.stderr)
        return {}
    table = data.get("tool", {}).get("wildlint", {})
    if not isinstance(table, dict):
        return {}
    for key in set(table) - _CONFIG_KEYS:
        print(
            f"{candidate}: unknown [tool.wildlint] key {key!r} ignored", file=sys.stderr
        )
    return table


def _build_parser() -> argparse.ArgumentParser:
    from . import __version__

    rules = ", ".join(f"{c.code} ({c.name}, {c.tier})" for c in CHECKERS)
    templates = ", ".join(f"{t.code} ({t.name})" for t in TEMPLATES)
    parser = argparse.ArgumentParser(
        prog="wildlint",
        description="Static checks distilled from real upstream bugs. "
        f"Rules: {rules}. Property-test templates: {templates}.",
    )
    parser.add_argument(
        "paths", nargs="*", default=["."], help="files or dirs (default: .)"
    )
    parser.add_argument(
        "--template",
        metavar="NAME",
        help="print a ready-to-paste property-test for a class that resists a "
        f"static rule ({templates}), then exit. Customize with "
        "--func/--import-from/--base.",
    )
    parser.add_argument(
        "--func",
        default="humanize",
        help="function name to test in the rendered --template (default: humanize)",
    )
    parser.add_argument(
        "--import-from",
        dest="import_from",
        default="yourmodule",
        help="module to import --func from in the rendered --template",
    )
    parser.add_argument(
        "--inverse",
        default="decode",
        help="inverse function name for round-trip templates, e.g. --inverse "
        "decodebytes (default: decode; ignored by unary templates)",
    )
    parser.add_argument(
        "--base",
        type=int,
        default=1000,
        help="unit radix for the rendered --template: 1000 (SI) or 1024 (bytes)",
    )
    parser.add_argument(
        "--pedantic",
        action="store_true",
        default=None,
        help="also run opt-in higher-false-positive rules "
        "(overridable via [tool.wildlint])",
    )
    parser.add_argument(
        "--select",
        metavar="CODES",
        default=None,
        help="comma-separated rule codes to run exclusively, e.g. WL001,WL002 "
        "(overridable via [tool.wildlint])",
    )
    parser.add_argument(
        "--no-default-exclude",
        action="store_true",
        help="do not skip common junk dirs (.venv, __pycache__, build, ...) when "
        "walking directories",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        metavar="GLOB",
        default=None,
        help="additional path glob to exclude (repeatable); also set via "
        "[tool.wildlint] exclude",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.template:
        tmpl = get_template(args.template)
        if tmpl is None:
            known = ", ".join(f"{t.code}/{t.name}" for t in TEMPLATES)
            print(
                f"unknown template {args.template!r}; known: {known}", file=sys.stderr
            )
            return 2
        print(
            tmpl.render(
                func=args.func,
                import_from=args.import_from,
                base=args.base,
                inverse=args.inverse,
            ),
            end="",
        )
        return 0

    config = _load_config(Path.cwd())

    # Precedence: CLI flag > [tool.wildlint] > built-in default. Flags use
    # default=None so we can tell "not given" apart from "given as False/empty".
    pedantic = (
        args.pedantic
        if args.pedantic is not None
        else bool(config.get("pedantic", False))
    )
    if args.select is not None:
        codes = {c.strip().upper() for c in args.select.split(",") if c.strip()} or None
    elif "select" in config:
        sel = config["select"]
        codes = {str(c).strip().upper() for c in sel if str(c).strip()} or None
    else:
        codes = None
    extra_excludes: list[str] = []
    if isinstance(config.get("exclude"), list):
        extra_excludes += [str(e) for e in config["exclude"]]
    if args.exclude:
        extra_excludes += args.exclude

    paths = args.paths or ["."]

    findings: list[Finding] = []
    errors: list[str] = []
    valid_paths: list[str] = []
    for raw in paths:
        if Path(raw).exists():
            valid_paths.append(raw)
        else:
            errors.append(f"{raw}: error: no such file or directory")
    for file in _iter_python_files(
        valid_paths,
        no_default_exclude=args.no_default_exclude,
        extra_excludes=tuple(extra_excludes),
    ):
        fnd, err = check_file(file, pedantic=pedantic, codes=codes)
        findings.extend(fnd)
        errors.extend(err)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "findings": [dataclasses.asdict(f) for f in findings],
                    "errors": errors,
                },
                indent=2,
            )
        )
    else:
        for f in findings:
            print(f)
        for e in errors:
            print(e, file=sys.stderr)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)

    return 1 if (findings or errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
