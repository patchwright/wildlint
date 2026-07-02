# wildlint ast-grep rules

Multi-language port of three wildlint checks (WL001, WL002, WL005) to
[ast-grep](https://ast-grep.github.io/) rule files, so the same real-bug classes
the Python linter catches in Python code can be scanned in Rust, Go, JavaScript,
and TypeScript too.

Each rule is distilled from a **real upstream bug** (a public PR). The Python
linter lives in `src/wildlint/checkers.py`; these `.yml` files are the
cross-language analogue, validated to fire on a minimal snippet of each rule's
real-bug positive.

## Install ast-grep

One of:

```bash
# npm (no project install required — scan with npx)
npm install -g @ast-grep/cli            # global
# OR use npx on demand (what this README's examples assume):
npx -y -p @ast-grep/cli sg --version    # -> ast-grep 0.44.0

# cargo
cargo install ast-grep-cli
```

> **Note:** on some Linux systems `/usr/bin/sg` is shadow-utils' set-group
> binary, **not** ast-grep. Check `sg --version` says `ast-grep X.Y.Z`; if it
> says `Usage: sg group ...`, use the full path or `npx` as above.

## Scan a target

There are two ways to run these rules. The **single-file `-r`** form is the
simplest and needs no project setup; the **project-config** form runs every
rule at once.

### 1. Single rule (no project setup)

```bash
# one rule file against one file
sg scan -r wildlint/ast-grep-rules/wl001-python.yml path/to/file.py

# JSON output for CI
sg scan -r wildlint/ast-grep-rules/wl001-python.yml path/to/file.py --json
```

`-r/--rule` takes a **single rule file** — it does not accept a directory or a
glob. To run several rules you either invoke `-r` once per file, or set up the
project form below.

### 2. All rules at once (project config)

ast-grep's multi-rule workflow wants a `sgconfig.yml` whose `ruleDirs` points
at a directory containing **only** rule `.yml` files (the config file itself
must live in its **parent**, or ast-grep will try to parse `sgconfig.yml` as a
rule and fail). Conventional layout:

```
my-sgconfig-dir/
├── sgconfig.yml        # contents:  ruleDirs: [rules]
└── rules/
    ├── wl001-python.yml
    ├── wl001-rust.yml
    └── ... (symlink or copy the .yml files here)
```

Then:

```bash
# from anywhere, pointing -c at the config:
sg scan -c path/to/my-sgconfig-dir/sgconfig.yml path/to/repo

# ast-grep applies every rule whose language matches each file's extension,
# so the Python rules won't fire on .rs files etc.
```

A one-liner to build that layout from this directory (no permanent changes to
your tree):

```bash
mkdir -p /tmp/wildlint-sg/rules &&
  ln -s "$PWD"/wildlint/ast-grep-rules/*.yml /tmp/wildlint-sg/rules/ &&
  printf 'ruleDirs: [rules]\n' > /tmp/wildlint-sg/sgconfig.yml &&
  sg scan -c /tmp/wildlint-sg/sgconfig.yml path/to/repo
```

## Rules

| Code  | Bug class | Python origin (real upstream fix) | Languages | Tier (`metadata.tier` / `guard_proven`) |
|-------|-----------|-----------------------------------|-----------|------|
| WL001 | `replace(marker, "")` guarded by `startswith`/`endswith` strips **every** occurrence, not just the prefix/suffix | nephila/giturlparse #149 (superseded by merged #152, `cf249252`) | Python, Rust, Go, JavaScript, TypeScript | **default / guard-proven** for Py/Rust/JS/TS; **pedantic candidate-only** for Go (tree-sitter-go has no `else_clause` node, so the else branch can't be excluded) |
| WL002 | `split(' ')` keeps empty tokens and does not collapse/trim whitespace | derek73/python-nameparser #164 (`5c1954718cd`) | Python, Rust, Go, JavaScript, TypeScript | pedantic (all languages) |
| WL005 | `not A and B or C` / `!A && B \|\| C` precedence — `and`/`&&` binds tighter than `or`/`\|\|`, so the leading negation guards only B | alexanderlukanin13/coolname #34 (open; bug on master `7f895eed330e`) | Python, Rust, Go, JavaScript, TypeScript | pedantic / advisory (all languages) |

### Provenance — what each rule was distilled from

- **WL001** — In giturlparse, `path.replace('/blob/', '')` was used under
  `if path.startswith('/blob/'):` to strip a prefix. `str.replace` removes
  *every* occurrence, so a value containing the marker twice
  (`/blob/x/blob/y`) was silently corrupted to `x/y`. The fix in PR #152
  switched to `str.removeprefix` / `str.removesuffix` (Python 3.9+). The same
  trap exists in every language with an all-occurrences replace: Rust
  `str::replace` (use `strip_prefix`/`strip_suffix`), Go
  `strings.ReplaceAll`/`strings.Replace(..., -1)` (use `TrimPrefix`/
  `TrimSuffix`), JS `.replaceAll` (use an explicit slice; `.replace` drops
  only the first match, which is the *other* half of this bug class).

- **WL002** — In python-nameparser, `name.split(' ')` was used where
  `.split()` was meant. `"a  b ".split(' ')` yields `['a','','b','']` (empty
  tokens kept, no run-collapsing, no trimming), while `.split()` collapses
  runs and trims ends. Fix merged in PR #164. Cross-language: Rust
  `str::split(' ')` (use `split_whitespace`), Go `strings.Split(s, " ")`
  (use `strings.Fields`), JS `s.split(' ')` (use `s.trim().split(/\s+/)`).
  Only an **exact single-space literal** fires — `'  '` or `','` is treated
  as a deliberate delimiter and left alone.

- **WL005** — In coolname, `__nocheck` was meant to suppress several checks
  via `not config.get(...) and self.a or self.b or self.c`. Because `and`
  binds tighter than `or`, this parsed as
  `(not config.get(...) and self.a) or self.b or self.c` — the `or self.b
  or self.c` branches escaped the guard and `_check_not_hanging` ran
  anyway. Advisory (most real-world hits are legitimate conditions); the
  Python linter marks it pedantic. If the guard should cover all branches,
  write `not A and (B or C)`.

## ast-grep gotchas these rules encode

Three ast-grep behaviours bit the prototypes and are baked into the rule
structure. They are non-obvious and worth knowing before you add a new rule:

1. **String-literal quote style is not normalized.** A pattern containing `""`
   will not match source containing `''`, and vice versa — even though they
   parse to the same AST node. Every rule that pins a string literal therefore
   lists **both quote styles** under `rule.any` (see `wl001-python.yml`,
   `wl002-python.yml`, `wl002-javascript.yml`, `wl002-typescript.yml`). For
   Rust/Go, where `""` is the only practical style, a single arm suffices.

2. **`language:` is per-rule and per-extension.** ast-grep's `JavaScript`
   language matches `.js` files **only**; `.ts` needs `language: TypeScript`
   and `.tsx` needs `language: Tsx`. There is no "JavaScript covers TypeScript"
   setting. Hence the JS/TS split: `wl00*-javascript.yml` + `wl00*-typescript.yml`.

3. **YAML parses a leading `!` as a tag.** A pattern like `!$A && $B || $C` must
   be **quoted** (`pattern: '!$A && $B || $C'`) or YAML rejects the file with
   `did not find expected alphabetic or numeric character`. All WL005
   Rust/Go/JS/TS rules quote the pattern for this reason.

### Bonus: ast-grep respects source-level grouping parens for boolean chains

The Python linter's WL005 has to recover parenthesization from the **token
stream** (`checkers.py:_chain_is_parenthesized`) because `ast.parse` discards
grouping parens — `(not a and b) or c` and the unparenthesized bug parse to the
same tree. ast-grep's structural pattern matcher, validated against 0.44.0,
**does** respect the distinction: `pattern: not $A and $B or $C` fires on the
bare form but **not** on `(not a and b) or c` (and the same holds for `&&`/`||`
in Rust, Go, JS, TS). The ast-grep WL005 rules are therefore *more precise*
than the Python linter's AST walk and need no token-space suppression.

## Guard precision vs. the Python linter

- **WL001 for Python/Rust/JS/TS proves the guard**, the same way the Python
  checker does: the replace call must sit inside the *consequence* (if-true
  branch) of an `if` guarded by `startsWith`/`starts_with` (or the `ends…`
  form) on the SAME receiver and marker literal, with `elif`/`else`/`else-if`
  branches excluded via `not: { inside: { stopBy: end, kind: else_clause } }`
  (Python also `elif_clause`). Those four ship at `metadata.tier: default`
  (`guard_proven: true`) — their hits are confirmed bugs, not candidates.
- **WL001 for Go is the exception — pedantic candidate-only.** tree-sitter-go
  has no `else_clause` node (the else body is a bare positional block), so the
  else branch cannot be structurally excluded and the guard cannot be proven.
  Treat Go `strings.ReplaceAll` hits as candidates for review against the
  surrounding `HasPrefix`/`HasSuffix`.
- **WL002/WL005 are pedantic/advisory in every language** (WL005 is paren-aware
  and tighter than the Python linter's AST walk, per the note above).

So: Python/Rust/JS/TS WL001 hits are confirmed bugs; all WL002, WL005, and Go
WL001 hits are candidates for human review.

## Layout

```
wildlint/ast-grep-rules/
├── README.md                  (this file)
├── wl001-python.yml
├── wl001-rust.yml
├── wl001-go.yml
├── wl001-javascript.yml       (.js)
├── wl001-typescript.yml       (.ts)
├── wl002-python.yml
├── wl002-rust.yml
├── wl002-go.yml
├── wl002-javascript.yml       (.js)
├── wl002-typescript.yml       (.ts)
├── wl005-python.yml
├── wl005-rust.yml
├── wl005-go.yml
├── wl005-javascript.yml       (.js)
└── wl005-typescript.yml       (.ts)
```

`.tsx` is not covered; add a `language: Tsx` variant of the TypeScript rule if
you scan tsx sources.

## Validation

Every rule here was actually run against a minimal real-bug-positive fixture
with **ast-grep 0.44.0** (via `npx -y -p @ast-grep/cli sg`, not pre-installed
on the authoring machine — `/usr/bin/sg` is shadow-utils' set-group binary,
not ast-grep). Confirmed:

- All 15 `.yml` files parse as valid `RuleConfig` (no `missing field` /
  `unknown field` / YAML-tag errors).
- Each rule fires on a minimal snippet of its real-bug positive:
  - WL001: `path.replace('/blob/', '')` under `startswith` → fires (Python
    single-quote, Python double-quote, Rust, Go, JS `.replaceAll`, TS).
  - WL002: `s.split(' ')` / `s.rsplit(' ', n)` → fires (all 5 languages).
  - WL005: `not a and b or c or d` / `!a && b || c` → fires (all 5 languages),
    and correctly does **not** fire on the parenthesized form
    `(not a and b) or c` / `(!a && b) || c`.
- Negative cases behave: WL001-Python is silent when the replacement is
  non-empty (`p.replace('/x/', '/y/')`).
- The project-config scan (`sg scan -c sgconfig.yml`) on a 5-file
  multi-language fixture fires 5 distinct rule ids, one per language.

Reproduce: `npx -y -p @ast-grep/cli sg scan -r wildlint/ast-grep-rules/wl001-python.yml <fixture.py>`.

## Adversarial validation (beyond the fixtures)

The pack has two layers of real-code pressure beyond the hand-written `sg test`
fixtures, mirroring the Python core's corpus gate. The 0.7.0 pack shipped two
language-semantics bugs precisely because neither existed yet.

- **`scripts/astgrep_corpus_diff.py`** runs the pack over a pinned multi-language
  real-world corpus (express, lodash, date-fns, gin, cobra, serde-json, jinja)
  and diffs finding counts vs `scripts/astgrep_corpus_baseline.json`. It **gates
  releases** (the `ast-grep-corpus` job in `release.yml`, where
  `build-and-publish: needs: [corpus, ast-grep-corpus]` blocks PyPI on drift) and
  runs on PRs that touch the pack (the `ast-grep` job in `ci.yml`). It fails
  closed: a clone/scan ERROR is distinguished from "0 findings" (returns 3, not a
  silent empty baseline). Local: `SG_BIN=sg python3 scripts/astgrep_corpus_diff.py`
  (exit 1 on drift, `--update` to re-cut).
- **`scripts/astgrep_drift_watch.py`** is a weekly advisory sweep
  (`.github/workflows/astgrep_drift_watch.yml`, Monday cron) over a broader
  MOVING-HEAD repo set; it fingerprints findings and opens a tracking issue for
  any not in the reviewed-accepted baseline (`scripts/astgrep_drift_baseline.json`).
  It **never blocks a release** — its role is to surface EMERGING real-world
  signal (the generalize-rule-never-run-it failure that shipped 0.7.0) so it
  can't recur unnoticed.

The division: `corpus_diff` catches rule REGRESSIONS against FROZEN pinned code
(pre-merge / pre-release); `drift_watch` catches EMERGING signal against MOVING
upstream (advisory, weekly). Rust corpus counts are expected-empty (the bug
shapes are vanishingly rare in idiomatic Rust) — Rust recall is owned by the `sg`
fixtures, not the corpus gate.

