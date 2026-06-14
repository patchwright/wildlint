"""Command-line entry point for wildlint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checkers import CHECKERS, Finding, check_source


def _iter_python_files(paths: list[str]):
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            yield from sorted(p.rglob("*.py"))
        elif p.suffix == ".py":
            yield p


def check_file(
    path: Path, *, pedantic: bool = False, codes: set[str] | None = None
) -> list[Finding]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        return check_source(source, str(path), pedantic=pedantic, codes=codes)
    except SyntaxError:
        return []


def _build_parser() -> argparse.ArgumentParser:
    from . import __version__

    rules = ", ".join(f"{c.code} ({c.name}, {c.tier})" for c in CHECKERS)
    parser = argparse.ArgumentParser(
        prog="wildlint",
        description="Static checks distilled from real upstream bugs. "
        f"Rules: {rules}.",
    )
    parser.add_argument(
        "paths", nargs="*", default=["."], help="files or dirs (default: .)"
    )
    parser.add_argument(
        "--pedantic",
        action="store_true",
        help="also run opt-in higher-false-positive rules",
    )
    parser.add_argument(
        "--select",
        metavar="CODES",
        help="comma-separated rule codes to run exclusively, e.g. WL001,WL002",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    codes = (
        {c.strip().upper() for c in args.select.split(",") if c.strip()}
        if args.select
        else None
    )
    paths = args.paths or ["."]

    findings: list[Finding] = []
    for file in _iter_python_files(paths):
        findings.extend(check_file(file, pedantic=args.pedantic, codes=codes))

    for f in findings:
        print(f)

    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
