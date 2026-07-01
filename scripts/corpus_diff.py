#!/usr/bin/env python3
"""Diff wildlint's finding counts over a pinned real-world corpus against a baseline.

This is the pre-release gate that internalizes the adversarial red-team: a
checker change that explodes false positives (e.g. WL005's v0.5.2 regression,
3 -> 34 hits on django) fails here before a tag is cut, instead of requiring an
external reviewer to notice after release. See RELEASING.md.

Usage (from the wildlint repo root):
    uv run python scripts/corpus_diff.py            # compare to baseline; exit 1 on drift
    uv run python scripts/corpus_diff.py --update    # rewrite baseline with current counts
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "scripts" / "corpus_baseline.json"

# pip-install spec -> import name (the site-packages dir wildlint scans).
# Pinned for reproducibility: a corpus package releasing a new version would
# otherwise drift the counts and mask a real checker change.
CORPUS = {
    "click==8.4.2": "click",
    "django==6.0.6": "django",
    "flask==3.1.3": "flask",
    "jinja2==3.1.6": "jinja2",
    "python-slugify==8.0.4": "slugify",
    "werkzeug==3.1.8": "werkzeug",
}
RULES = ["WL001", "WL002", "WL003", "WL004", "WL005"]


def _run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=REPO, capture_output=True, text=True, **kw)


def _count(imp: str, site_packages: Path) -> dict[str, int]:
    """One wildlint scan per package (--pedantic --format json), count per code."""
    src = site_packages / imp
    r = _run(["uv", "run", "wildlint", "--format", "json", "--pedantic", str(src)])
    try:
        findings = json.loads(r.stdout).get("findings", [])
    except json.JSONDecodeError:
        print(
            f"  ! could not parse JSON for {imp} (wildlint stdout: {r.stdout[:200]!r})",
            file=sys.stderr,
        )
        return {rule: -1 for rule in RULES}
    return {rule: sum(1 for f in findings if f.get("code") == rule) for rule in RULES}


def main() -> int:
    update = "--update" in sys.argv
    with tempfile.TemporaryDirectory() as venv:
        py = f"{venv}/bin/python"
        _run(["uv", "venv", venv, "--quiet"])
        inst = _run(["uv", "pip", "install", "--python", py, "--quiet", *CORPUS])
        if inst.returncode != 0:
            print("corpus install failed:\n" + inst.stderr, file=sys.stderr)
            return 3
        sp = subprocess.run(
            [py, "-c", "import site; print(site.getsitepackages()[0])"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        site_packages = Path(sp)
        live = {imp: _count(imp, site_packages) for imp in CORPUS.values()}

    if update:
        data = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
        data["counts"] = live  # preserves _comment / _pinned / etc.
        BASELINE.write_text(json.dumps(data, indent=2) + "\n")
        print(f"baseline rewritten: {BASELINE}")
        return 0

    expected = json.loads(BASELINE.read_text())["counts"]
    drift = []
    print(
        f"{'package':<10} " + " ".join(f"{r:>5}" for r in RULES) + "   (base -> live)"
    )
    for imp in CORPUS.values():
        cells = []
        for rule in RULES:
            base = expected[imp][rule]
            now = live[imp][rule]
            mark = "" if base == now else f" {base}->{now} *"
            if base != now:
                drift.append((imp, rule, base, now))
            cells.append(f"{now:>5}{mark}")
        print(f"{imp:<10} " + " ".join(cells))

    if drift:
        print("\ncorpus drift -- counts changed:", file=sys.stderr)
        for imp, rule, base, now in drift:
            print(f"  {imp} {rule}: {base} -> {now}", file=sys.stderr)
        print(
            "\nIf the change is intended (real fix, not an FP explosion), re-run with "
            "--update and record why in the commit message.",
            file=sys.stderr,
        )
        return 1
    print("\ncorpus stable: all counts match baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
