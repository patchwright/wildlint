# Releasing wildlint

Two questions, kept separate:

1. **Is it ready?** — the checklist below. Deterministic; run it every time.
2. **Does it ship?** — a published PyPI version is *permanent* (yankable, not
   deletable) and ships under the **patchwright** identity. So:
   - **new public surface** (new WL/WP rule, new exported symbol, behavior
     change) → assemble the filled checklist + diff, get a human go, then
     publish.
   - **routine patch** (test-only, docs, a fix that doesn't change a rule's
     surface) → green checklist → publish + report.

The checklist replaces "because I said so." If an item is red, it doesn't ship —
no exceptions for vibes. A gate with substance, not caution dressed as a rule.

## Readiness checklist — every release

- [ ] full suite green: `PYTHONPATH=src python -m pytest -q`
- [ ] `python -m ruff check .` clean
- [ ] `python -m ruff format --check .` clean
- [ ] **provenance pinned** to a real upstream bug with SHAs (pre-fix commit +
      fixed commit); recorded in the rule's docstring + README row
- [ ] **build-honesty gate**: the checker goes RED on the real pre-fix source and
      GREEN on the fixed source — run against fetched upstream, not only a
      synthetic repro.
- [ ] version bumped in `src/wildlint/__init__.py` **and** `pyproject.toml`
      (semver: new rule/surface = minor; internal fix = patch)
- [ ] new public symbols exported from `src/wildlint/__init__.py` (`__all__`)
- [ ] `python -m build` succeeds; `.venv/bin/twine check dist/*` PASSED
- [ ] `git status` clean apart from the release diff (no stray unrelated changes)
- [ ] **push access verified** — ensure you can push to `patchwright/wildlint`
      (via `gh auth`, a credential helper, or a PAT stored outside the repo)

### additionally — WL static rules (lint that fires on real code)

- [ ] **corpus_diff gate green**: `uv run python scripts/corpus_diff.py` shows no
      drift vs `scripts/corpus_baseline.json` (finding counts over a pinned
      django/werkzeug/jinja2/flask/click/slugify corpus). A jump — e.g. a WL005
      regression taking django from 3 to 34 hits — fails here before the tag, not
      after release via external red-teaming. If a count change is intended (a
      real fix), re-run with `--update` and record why in the commit. Default
      tier must stay FP≈0 on the corpus; pedantic-tier counts are tracked but
      advisory. (Automates the old "FP-corpus swept" item; the WL004 httpie
      46→0 fix is the precedent.)

### additionally — WP property templates (opt-in property tests)

- [ ] catches the distilled real bug (faithful positive reproduction)
- [ ] silent on a correct implementation (negative case)
- [ ] skips unrelated crashes (a different exception is a different bug class)
- [ ] rendered `--template` is valid Python (`ast.parse`) and imports the pair

## Publish mechanics (OIDC trusted publishing — no token in the workflow)

Push a tag → `.github/workflows/release.yml` builds + publishes via trusted
publishing (no stored PyPI token).

```bash
git commit -am "release: vX.Y.Z"        # or stage precisely
git tag -a vX.Y.Z -m "vX.Y.Z — <one-line>"
git push origin main vX.Y.Z             # gh auth / credential helper handles auth
```

`skip-existing: true` makes a re-tag idempotent (a version already on PyPI is a
no-op). Release notes live in the **tag annotation** (or an optional GitHub
Release) — there is no CHANGELOG file by project convention.

## Post-publish smoke (runs AFTER publish — the closing item)

- [ ] fresh install in a clean venv: `pip install wildlint==X.Y.Z`
- [ ] `wildlint --version` reports the new version
- [ ] the new rule renders / fires: `wildlint --template <name> ...`
- [ ] `python -c "import wildlint; print(wildlint.__version__, [t.code for t in wildlint.TEMPLATES])"`

## What this gate is not

- Not a substitute for judgment on *what* ships under patchwright's name — that
  is the human-go tier for new surfaces.
- Not static — amend this file when the release process changes, so the gate
  reflects reality rather than rotting into a fiction.
