# Contributing to wildlint

wildlint grows one real bug at a time. The bar for a new rule: a **concrete
upstream bug** it was distilled from, the smallest **low-false-positive** AST
signature, and positive+negative tests that mirror the wild bug. See the "Adding
a rule" section of the README.

## AST checker (Python core)
1. Append a checker class to `src/wildlint/checkers.py` — `code`, `name`,
   `tier`, and `check(tree, path, source) -> list[Finding]`. Register it in
   `CHECKERS`. The `Checker` Protocol documents the interface; mypy (CI `type`
   job) verifies it.
2. Add positive+negative tests in `tests/test_wildlint.py`. Negative cases (the
   legitimate code the rule must stay silent on) are load-bearing — a rule that
   fires on correct code is a regression.
3. `python -m pytest -q` must stay green; the release-gating Python corpus
   (`scripts/corpus_diff.py`) catches real-code count drift.

## ast-grep cross-language port
- One rule file per language in `ast-grep-rules/`. **Verify with `sg test` AND by
  running `sg scan` against real OSS** — the 0.7.0 pack shipped two language-
  semantics bugs because a port was tested only against self-authored fixtures.
  See `ast-grep-rules/README.md`.
- The corpus gate (`scripts/astgrep_corpus_diff.py`) and weekly drift-watch
  (`scripts/astgrep_drift_watch.py`) provide real-code pressure. Re-cut the
  baseline with `--update` after a *deliberate* rule change and record why in the
  commit; never `--update` to silence a scan error (the script fails closed).

## Release
Tags trigger `release.yml`: the `corpus` and `ast-grep-corpus` gates must pass
before PyPI trusted publishing. Bump `version` in `pyproject.toml` and
`__version__` in `src/wildlint/__init__.py` together, and bump the README
pre-commit `rev:` to match the new tag.

Be honest about provenance in the README rules table (self-submitted vs
independently merged upstream).
