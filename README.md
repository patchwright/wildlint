# wildlint

[![CI](https://github.com/patchwright/wildlint/actions/workflows/ci.yml/badge.svg)](https://github.com/patchwright/wildlint/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/wildlint.svg)](https://pypi.org/project/wildlint/)

Static checks for bug classes off-the-shelf linters (ruff/flake8/pylint) don't
cover — the kind that look like ordinary, working code.

**What this is, honestly:** a *precision* tool for a handful of specific bug
classes, not a general-purpose linter. Its value is measured two ways —
near-zero false positives on already-clean code (the default tier is silent on
mature, heavily-linted codebases like django/click/flask by design), and
catching the bug where it exists (WL004, for example, finds a real dead
`argparse` flag in python-slugify that ruff does not). It is **not** a
high-recall scanner: on most real-world code it finds nothing, and that is the
point of a low-noise rule set. If a bug could not be turned into a low-noise
rule it is documented as [not shipped](#bugs-considered-but-not-shipped) rather
than added as noise.

Every rule traces to a concrete upstream bug, but how much *independent*
validation each one has varies — and that's shown plainly in the provenance
column of the [rules table](#rules) rather than implied by uniform-looking
citation: two were merged by unaffiliated maintainers, one was independently
duplicated by a stranger, and two are still self-submitted and unreviewed.

## What it catches

Real bugs, phrased the way you'd search them:

- **"my argparse flag parses but does nothing"** — an option whose `dest` is never read (WL004)
- **`x.replace(prefix, "")` corrupts values containing the marker twice** — meant `str.removeprefix`/`removesuffix` (WL001)
- **`s[-k]` raises IndexError on short inputs** — deep negative indexing (WL003)
- **`millify(999999)` returns `'1000k'` not `'1M'`** — rounding rollover in number/byte humanizers (WP001)
- **`.replace(second=0)` crashes on a bare `datetime.date`** — datetime-subclass confusion (WP002)

## Install

```bash
pip install wildlint
```

## Use

```bash
wildlint path/to/code            # scan a file or directory (default: .)
wildlint --select WL001,WL002 src/
wildlint --pedantic src/         # also run opt-in, higher-false-positive rules
wildlint --format json src/      # machine-readable output
```

When walking a directory, common junk (`.venv`, `__pycache__`, `build`, `dist`,
`.git`, `node_modules`, …) is skipped automatically — pass `--no-default-exclude`
to scan everything, or `--exclude 'glob/*'` to drop more. Explicit file and
directory arguments are always scanned as-is. Silence a finding inline with a
trailing `# noqa` (all codes) or `# noqa: WL001,WL002` (specific) — placed on
the line where the finding is reported (for a multi-line call, the line of the
flagged expression, not the closing parenthesis, matching flake8/ruff).

Exits non-zero when anything is found **or** a file could not be analysed (a
syntax error, non-UTF-8, or a missing path); the diagnostic goes to stderr and
findings stay on stdout, so it drops straight into CI or a pre-commit hook.

### pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/patchwright/wildlint
    rev: v0.6.2
    hooks:
      - id: wildlint
```

### CI (GitHub Actions)

```yaml
- run: pip install wildlint
- run: wildlint src/
```

### Configuration

`[tool.wildlint]` in `pyproject.toml` sets defaults that CLI flags override:

```toml
[tool.wildlint]
pedantic = true          # run opt-in rules by default
select = ["WL001"]       # restrict to these codes
exclude = ["vendor/*"]   # additional path globs to skip
```

## Rules

| Code  | Tier     | Catches | Provenance & independent validation |
|-------|----------|---------|-------------------------------------|
| WL001 | default  | `x.replace(P, "")` guarded by `x.startswith(P)`/`endswith(P)` — removes *every* occurrence, silently corrupting values that contain the marker twice. Meant `str.removeprefix`/`removesuffix`. | ✅ **merged** by the maintainer — [giturlparse#152](https://github.com/nephila/giturlparse/pull/152) |
| WL002 | pedantic | `s.split(' ')` where `s.split()` was meant — keeps empty tokens and skips whitespace collapsing/trimming, leaking blanks downstream. Advisory and opt-in: only an exact single-space literal fires, and it's frequently intentional. | ✅ **merged** by the maintainer — [nameparser#164](https://github.com/derek73/python-nameparser/pull/164) |
| WL003 | pedantic | `x[-k]` with `k >= 2` — `IndexError` when the sequence is shorter than `k`. Opt-in because deep negative indexing is often provably safe from context the checker can't see. | ⏳ open, self-submitted — **no independent review yet** — [num2words#661](https://github.com/savoirfairelinux/num2words/pull/661) |
| WL004 | default  | An `argparse` option whose `dest` is never read — the flag parses, then silently vanishes. Fires only when *sibling* dests on the same namespace **are** read in the file (so consumption is local and the gap is an oversight). Bails on `vars()`/`getattr`/`**`-splat namespaces and on definitions-only files. | ✅ **independently duplicated** by an unaffiliated developer (the strongest validation here) — [slugify#176](https://github.com/un33k/python-slugify/pull/176), reported [#175](https://github.com/un33k/python-slugify/issues/175) |
| WL005 | pedantic (advisory) | `not A and B or C` — `and` binds tighter than `or`, so the leading `not A and` guards only B, not the trailing `or` branches. **Advisory**: flags precedence ambiguity for review (most hits are legitimate conditions, not bugs); write `not A and (B or C)` if the guard should cover all branches. Explicitly parenthesized and-chains are recognized and suppressed. | ⏳ open, self-submitted — **no independent review yet** — [coolname#34](https://github.com/alexanderlukanin13/coolname/pull/34) |

**On the provenance column:** ✅ = the fix was accepted (or independently
re-discovered) by someone with no connection to this tool — the strongest
evidence a rule's bug class is real. ⏳ = the PR is still open and unreviewed;
the rule may well be correct, but right now the only validation is the author's.
Treat those two (WL003, WL005) with commensurate caution.

The **default** tier is WL001 and WL004 — both have effectively zero false
positives. WL002, WL003, and WL005 are opt-in via `--pedantic`: real bug classes,
but they also fire on legitimate code, so the default stays strictly precision.

Each rule is verified against the *actual pre-fix source* of the project it came
from — see the tests, and the rule docstrings in `src/wildlint/checkers.py`.

## Property-test templates

Some bug classes have no stable AST signature — the same wrong behaviour is
reached by different code each time, so any static rule broad enough to catch
them all also flags mountains of correct code. The archetype is the
**rounding-rollover** bug in number / byte / SI-prefix humanizers
([boltons#403](https://github.com/mahmoud/boltons/pull/403),
[millify#13](https://github.com/azaitsev/millify/pull/13),
[numerize#17](https://github.com/davidsa03/numerize/pull/17),
[si-prefix#17](https://github.com/cfobel/si-prefix/pull/17)): four distinct
implementations of *one* invariant break (`<=`-vs-`<`, a missing carry after
rounding, rounding an unrounded boundary). `millify(999999)` returns `'1000k'`
instead of `'1M'`.

What they share is a falsifiable **property**: a humanizer must never emit a
mantissa `>= base` while a larger unit is still available. wildlint ships that
check two ways.

**Run it directly** (dependency-free, in your own test suite or CI):

```python
from wildlint.property_templates import find_rollover
from millify import millify

def test_no_rounding_rollover():
    violations = find_rollover(millify, base=1000)  # 1000=SI, 1024=bytes
    assert not violations, "\n".join(str(v) for v in violations)
```

`find_rollover` sweeps the dangerous boundary inputs (values that round *up*
across a unit boundary) and returns the concrete violations. Pass `units=[...]`
(small→large) for an exact check that won't flag legitimate overflow at the
largest unit.

The same two-way model covers the **date/datetime-subclass confusion** bug
([deepdiff#602](https://github.com/qlustered/deepdiff/pull/602)): a function
written assuming `datetime.datetime` that calls `.replace(second=0,
microsecond=0)` (or reads `.hour`) crashes on a bare `datetime.date`, because
`datetime` is a *subclass* of `date` — so any `isinstance(x, date)` dispatch
admits dates the code cannot handle.

```python
from wildlint.property_templates import find_date_kwargs

def test_does_not_crash_on_date():
    violations = find_date_kwargs(truncate)  # probes with a bare date and time
    assert not violations, "\n".join(str(v) for v in violations)
```

`find_date_kwargs` records only `TypeError`/`AttributeError` whose message cites
a time-only field (`hour`, `minute`, `second`, …); an unrelated crash is a
different class and is skipped.

**Or render a paste-ready template:**

```bash
wildlint --template rollover --func millify --import-from millify --base 1000
wildlint --template date-time-kwargs --func truncate --import-from deepdiff
wildlint --template roundtrip --func encodebytes --import-from base62 --inverse decodebytes
```

| Code  | Catches | Distilled from |
|-------|---------|----------------|
| WP001 | A humanizer emits a mantissa `>= base` while a larger unit is available (`'1000k'` instead of `'1M'`) because the unit is chosen before the mantissa is rounded. | boltons#403, millify#13, numerize#17, si-prefix#17 |
| WP002 | A function accepting a temporal value unconditionally reads a datetime-only field (`.replace(second=0, microsecond=0)` or `.hour`) and crashes on a bare `datetime.date` — `datetime` is a subclass of `date`, so `isinstance(x, date)` admits dates the code can't handle. | deepdiff#602 |
| WP003 | An encode/decode pair is not mutually inverse (`inverse(forward(x)) != x`). The archetype is a byte↔string codec that routes through an integer (`int.from_bytes`), so leading `0x00` bytes carry no weight and are silently dropped: `decodebytes(encodebytes(b"\x00\x01")) == b"\x01"`. | suminb/base62#22 |

## Bugs considered but not shipped

Some real bugs do not generalize into a low-false-positive static rule. They are
recorded in `NON_GENERALIZED` in `checkers.py` so the reasoning is preserved:

- **break-vs-continue** ([mnamer#371](https://github.com/jkwill87/mnamer/pull/371)) — whether `break` should be `continue` is entirely loop-intent dependent.
- **sign-doubling** ([humanize#326](https://github.com/python-humanize/humanize/pull/326)) — a numeric-formatting concern, not a syntactic pattern.
- **validation-branch-order** ([validators#463](https://github.com/python-validators/validators/pull/463)) — specific to one parser's control flow.
- **radix-from-ignored-param** ([shortuuid#115](https://github.com/skorokithakis/shortuuid/pull/115)) — requires matching a docstring contract to the implementation.
- **rng-from-unordered-set** — iterating a set into a `random` population (directly, or via `list(some_set)` feeding `random.choices` weights) is non-deterministic across processes: `PYTHONHASHSEED` varies per worker, so set iteration order — and item↔weight alignment — changes run to run. The bare form (`random.choice({1,2,3})`) is rare; the real class (`set`→`list`→positional use) is only visible cross-process and is best caught by a reproducibility property test (run twice under differing `PYTHONHASHSEED`, assert identical output), not a static rule.

## Adding a rule

A checker is any object with `code`, `name`, `tier`, and
`check(tree, path, source=None) -> list[Finding]`. Append an instance to `CHECKERS` in
`checkers.py` and add positive/negative tests mirroring the wild bug. That's the
whole extension surface — the suite grows one real bug at a time.

## License

MIT.
