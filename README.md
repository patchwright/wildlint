# wildlint

[![CI](https://github.com/patchwright/wildlint/actions/workflows/ci.yml/badge.svg)](https://github.com/patchwright/wildlint/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/wildlint.svg)](https://pypi.org/project/wildlint/)

Static checks distilled from **real upstream bugs** — the kind off-the-shelf
linters miss because they look like ordinary, working code.

Every rule here was born from a concrete bug that was found and fixed in a
public project, then generalized to the smallest static check that still catches
the *class* without flooding you with false positives. If a bug could not be
turned into a low-noise rule, it is documented as not-shipped rather than added
as noise (see [Not shipped](#bugs-considered-but-not-shipped)).

## Install

```bash
pip install wildlint
```

## Use

```bash
wildlint path/to/code        # scan a file or directory (default: .)
wildlint --select WL001,WL002 src/
wildlint --pedantic src/     # also run opt-in, higher-false-positive rules
```

Exits non-zero when anything is found, so it drops straight into CI or a
pre-commit hook.

### pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/patchwright/wildlint
    rev: v0.1.0
    hooks:
      - id: wildlint
```

### CI (GitHub Actions)

```yaml
- run: pip install wildlint
- run: wildlint src/
```

## Rules

| Code  | Tier     | Catches | Distilled from |
|-------|----------|---------|----------------|
| WL001 | default  | `x.replace(P, "")` guarded by `x.startswith(P)`/`endswith(P)` — removes *every* occurrence, silently corrupting values that contain the marker twice. Meant `str.removeprefix`/`removesuffix`. | [nephila/giturlparse#149](https://github.com/nephila/giturlparse/pull/149) |
| WL002 | default  | `s.split(' ')` where `s.split()` was meant — keeps empty tokens and skips whitespace collapsing/trimming, leaking blanks downstream. Advisory: only an exact single-space literal fires. | [derek73/python-nameparser#164](https://github.com/derek73/python-nameparser/pull/164) |
| WL003 | pedantic | `x[-k]` with `k >= 2` — `IndexError` when the sequence is shorter than `k`. Opt-in because deep negative indexing is often provably safe from context the checker can't see. | [savoirfairelinux/num2words#661](https://github.com/savoirfairelinux/num2words/pull/661) |

Each rule is verified against the *actual pre-fix source* of the project it came
from — see the tests, and the rule docstrings in `src/wildlint/checkers.py`.

## Bugs considered but not shipped

Some real bugs do not generalize into a low-false-positive static rule. They are
recorded in `NON_GENERALIZED` in `checkers.py` so the reasoning is preserved:

- **break-vs-continue** ([mnamer#371](https://github.com/jkwill87/mnamer/pull/371)) — whether `break` should be `continue` is entirely loop-intent dependent.
- **sign-doubling** ([humanize#326](https://github.com/python-humanize/humanize/pull/326)) — a numeric-formatting concern, not a syntactic pattern.
- **validation-branch-order** ([validators#463](https://github.com/python-validators/validators/pull/463)) — specific to one parser's control flow.
- **radix-from-ignored-param** ([shortuuid#115](https://github.com/skorokithakis/shortuuid/pull/115)) — requires matching a docstring contract to the implementation.

## Adding a rule

A checker is any object with `code`, `name`, `tier`, and
`check(tree, path) -> list[Finding]`. Append an instance to `CHECKERS` in
`checkers.py` and add positive/negative tests mirroring the wild bug. That's the
whole extension surface — the suite grows one real bug at a time.

## License

MIT.
