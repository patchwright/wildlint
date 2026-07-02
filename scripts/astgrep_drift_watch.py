#!/usr/bin/env python3
"""Weekly drift-watch: scan MOVING upstream repos with the current ast-grep pack
and surface NEW findings for human review.

Distinct role from astgrep_corpus_diff.py (pinned tags, GATES releases):
  - corpus_diff catches RULE regressions against frozen code (a rule edit that
    changes counts fails the gate pre-publish).
  - drift_watch catches EMERGING real-world signal against moving code: a rule
    starting to match new patterns in upstream OSS — either a genuine bug class
    surfacing in the wild (interesting) or a rule that's broader than intended
    (FP risk). Advisory: it opens a tracking issue, never blocks a release.

This converts the reviewer's "continued spot-checking if more languages or rules
get added" from a human-memory chore into a mechanism -- the 0.7.0 failure mode
(generalize a rule, never run it against real non-Python code) can't recur
unnoticed.

Usage (from the wildlint repo root):
    SG_BIN=sg python3 scripts/astgrep_drift_watch.py           # report new findings (exit 1 if any)
    SG_BIN=sg python3 scripts/astgrep_drift_watch.py --accept  # add the CURRENT live set to baseline

The first run after adding repos/rules should be --accept (seed the baseline to
the current clean state); subsequent runs report only the delta.
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
BASELINE = REPO / "scripts" / "astgrep_drift_baseline.json"
SG = os.environ.get("SG_BIN", "sg")

# Moving upstream (default-branch HEAD). Intentionally broader than the pinned
# corpus so more real code faces the rules every week.
WATCH = [
    "expressjs/express",
    "lodash/lodash",
    "cheeriojs/cheerio",
    "date-fns/date-fns",
    "gin-gonic/gin",
    "spf13/cobra",
    "urfave/cli",
    "serde-rs/json",
]


def _run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def _fingerprints(clone_root: Path, repo_name: str) -> list[str] | None:
    """Returns sorted fingerprints, [] for a genuine-empty repo, None on error."""
    r = _run([SG, "scan", "-c", str(SGCONFIG), "--json", str(clone_root)])
    if r.returncode != 0:
        print(f"  ! sg failed for {repo_name}: {r.stderr[:160]!r}", file=sys.stderr)
        return None
    try:
        hits = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    fps: set[str] = set()
    for h in hits:
        f = h.get("file", "")
        try:
            rel = str(Path(f).relative_to(clone_root))
        except ValueError:
            rel = Path(f).name
        line = h.get("range", {}).get("start", {}).get("line", "?")
        fps.add(f"{h.get('ruleId', '?')}|{rel}|{line}")
    return sorted(fps)


def main() -> int:
    accept = "--accept" in sys.argv
    live: dict[str, list[str]] = {}
    errored: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for spec in WATCH:
            dest = td / spec.replace("/", "__")
            print(f"  clone {spec} (HEAD) …", file=sys.stderr)
            c = _run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    f"https://github.com/{spec}.git",
                    str(dest),
                ]
            )
            if c.returncode != 0:
                print(f"  ! clone failed {spec}:\n{c.stderr[:200]}", file=sys.stderr)
                continue
            fps = _fingerprints(dest, spec)
            if fps is None:
                errored.append(spec)
                continue
            live[spec] = fps

    accepted = (
        json.loads(BASELINE.read_text()).get("fingerprints", {})
        if BASELINE.exists()
        else {}
    )
    new: dict[str, list[str]] = {}
    for repo, fps in live.items():
        acc = set(accepted.get(repo, []))
        delta = [f for f in fps if f not in acc]
        if delta:
            new[repo] = delta

    if accept:
        if errored:
            # Refuse to reseed: writing `live` now would silently drop the
            # errored repos' accepted fingerprints, masking all their future
            # drift. The more dangerous half of the error-vs-empty gap.
            print(
                f"  ! refusing --accept: sg scan errored for {errored}; re-seeding "
                "now would drop those repos' accepted findings. Fix the scan and rerun.",
                file=sys.stderr,
            )
            return 3
        BASELINE.write_text(
            json.dumps(
                {
                    "_note": "Reviewed-accepted ast-grep findings on moving upstream HEAD. "
                    "Re-seed with --accept after triaging new findings.",
                    "fingerprints": live,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(f"baseline rewritten: {BASELINE}", file=sys.stderr)
        return 0

    if not new:
        print("no new findings: live matches accepted baseline.")
        return 0

    total = sum(len(v) for v in new.values())
    print(f"NEW FINDINGS ({total}) not in accepted baseline:")
    for repo, fps in new.items():
        print(f"\n## {repo}")
        for f in fps:
            rid, rel, line = f.split("|", 2)
            print(f"  - {rid} at {rel}:{line}")
    print(
        "\nTriage at each repo's HEAD. If genuine bug patterns, note them; if false "
        "positives, fix the rule. Then re-run with --accept to silence them.",
        file=sys.stderr,
    )
    return 1  # non-zero so the workflow can detect "new findings to triage"


if __name__ == "__main__":
    sys.exit(main())
