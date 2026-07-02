#!/usr/bin/env python3
"""Diff the ast-grep rule pack's finding counts over a pinned multi-language
real-world corpus against a baseline.

This is the ast-grep analogue of scripts/corpus_diff.py. It exists because the
0.7.0 pack shipped two language-semantics bugs (JS .replace vs .replaceAll, Go
strings.Replace n==1) that the Python-only corpus gate could not catch: the pack
had no adversarial pressure against real non-Python code, and the hand-written
sg test cases encoded the author's (wrong) mental model rather than the
languages' actual semantics. Running the rules against pinned real repos and
diffing the counts closes that gap -- a rule edit that explodes false positives
(or drops real catches) fails here before a tag is cut.

Usage (from the wildlint repo root):
    SG_BIN=sg python3 scripts/astgrep_corpus_diff.py            # compare; exit 1 on drift
    SG_BIN=sg python3 scripts/astgrep_corpus_diff.py --update   # rewrite baseline

Requires the ast-grep CLI (`sg`) on PATH; in CI it is installed via
`npm install -g @ast-grep/cli`. Override the binary with $SG_BIN for local dev.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SGCONFIG = REPO / "sgconfig.yml"
BASELINE = REPO / "scripts" / "astgrep_corpus_baseline.json"
SG = os.environ.get("SG_BIN", "sg")

# owner/repo -> git ref (release tag for reproducibility). One+ per ast-grep
# language so every rule family faces real-code pressure. A ref that moves would
# drift counts and mask a real rule change, so prefer immutable tags.
CORPUS = {
    "expressjs/express": "4.19.2",      # JavaScript
    "lodash/lodash": "4.17.21",         # JavaScript
    "date-fns/date-fns": "v3.6.0",      # TypeScript
    "gin-gonic/gin": "v1.10.0",         # Go
    "spf13/cobra": "v1.8.1",            # Go
    "serde-rs/json": "v1.0.128",        # Rust
}


def _run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def _counts_for(path: Path) -> dict[str, int]:
    """sg scan the cloned repo, count findings per ruleId. Returns {} on error."""
    r = _run([SG, "scan", "-c", str(SGCONFIG), "--json", str(path)])
    if r.returncode != 0:
        print(f"  ! sg scan failed for {path.name}: {r.stderr[:200]!r}", file=sys.stderr)
        return {}
    try:
        hits = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"  ! no JSON for {path.name}: {r.stdout[:200]!r}", file=sys.stderr)
        return {}
    counts: dict[str, int] = {}
    for h in hits:
        rid = h.get("ruleId", "?")
        counts[rid] = counts.get(rid, 0) + 1
    return counts


def main() -> int:
    update = "--update" in sys.argv
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        live: dict[str, dict[str, int]] = {}
        for spec, ref in CORPUS.items():
            owner_repo = spec  # owner/repo
            dest = td / owner_repo.replace("/", "__")
            url = f"https://github.com/{owner_repo}.git"
            print(f"  clone {owner_repo}@{ref} …", file=sys.stderr)
            c = _run(["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)])
            if c.returncode != 0:
                print(f"  ! clone failed for {owner_repo}@{ref}:\n{c.stderr}", file=sys.stderr)
                return 3
            live[owner_repo] = _counts_for(dest)

    if update:
        data = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
        data["counts"] = live
        data["_note"] = (
            "ast-grep rule-pack counts over a pinned multi-language corpus. "
            "Re-cut with --update only after a deliberate rule change; record why."
        )
        BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        print(f"baseline rewritten: {BASELINE}", file=sys.stderr)
        return 0

    expected = json.loads(BASELINE.read_text())["counts"]
    drift = []
    all_rules = sorted({r for repo in (live | expected) for r in live.get(repo, {}) | expected.get(repo, {})})
    print(f"{'repo':<22} " + " ".join(f"{r[:14]:>14}" for r in all_rules) + "   (base -> live)")
    for repo in expected:
        cells = []
        for r in all_rules:
            base = expected.get(repo, {}).get(r, 0)
            now = live.get(repo, {}).get(r, 0)
            mark = "" if base == now else f" {base}->{now} *"
            if base != now:
                drift.append((repo, r, base, now))
            cells.append(f"{now:>14}{mark}")
        print(f"{repo:<22} " + " ".join(cells))

    if drift:
        print("\nast-grep corpus drift -- counts changed:", file=sys.stderr)
        for repo, r, base, now in drift:
            print(f"  {repo} {r}: {base} -> {now}", file=sys.stderr)
        print(
            "\nIf intended (real rule fix, not an FP explosion), re-run with --update "
            "and record why in the commit message.",
            file=sys.stderr,
        )
        return 1
    print("\nast-grep corpus stable: all counts match baseline.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
