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

| Code  | Bug class | Python origin (real upstream fix) | Languages here |
|-------|-----------|-----------------------------------|----------------|
| WL001 | `replace(marker, "")` guarded by `startswith`/`endswith` strips **every** occurrence, not just the prefix/suffix | nephila/giturlparse #149 (superseded by merged #152, `cf249252`) | Python, Rust, Go, JavaScript, TypeScript |
| WL002 | `split(' ')` keeps empty tokens and does not collapse/trim whitespace | derek73/python-nameparser #164 (`5c1954718cd`) | Python, Rust, Go, JavaScript, TypeScript |
| WL005 | `not A and B or C` / `!A && B \|\| C` precedence — `and`/`&&` binds tighter than `or`/`\|\|`, so the leading negation guards only B | alexanderlukanin13/coolname #34 (open; bug on master `7f895eed330e`) | Python, Rust, Go, JavaScript, TypeScript |

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

## What these rules do NOT do (vs. the Python linter)

- **WL001 does not prove the guard holds.** The Python checker walks the `if`
  body and confirms the `replace` runs under a `startswith`/`endswith` on the
  same receiver and literal. ast-grep fires on the bare `replace(marker, "")`
  call site; reviewers must confirm the surrounding guard. A single ast-grep
  rule cannot AND a call with an enclosing conditional in one pattern.
- **WL002/WL005 have the same precision as the Python linter** (WL005 is
  tighter, per the note above).

Treat ast-grep hits as **candidates for human review**, not confirmed bugs —
the same posture as the Python linter's `PEDANTIC` tier.

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

