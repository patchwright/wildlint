"""Detector registry for wildlint.

Each checker is distilled from a *real* bug found in the wild (a public upstream
PR), generalized into the smallest static rule that still catches the class
without drowning the user in false positives. Checkers that could only be made
to fire with an unacceptable false-positive rate are documented in
``NON_GENERALIZED`` rather than shipped.

A checker is any object exposing ``code``, ``name``, ``tier`` and a
``check(tree, path, source=None) -> list[Finding]`` method. ``source`` is the
raw text the tree was parsed from (``None`` when unavailable); checkers that
need to inspect grouping parentheses -- which ``ast.parse`` discards -- use it.
Register one by appending an instance to ``CHECKERS``.
"""

from __future__ import annotations

import ast
import tokenize
from dataclasses import dataclass
from io import StringIO

DEFAULT = "default"  # low false-positive; on unless deselected
PEDANTIC = "pedantic"  # higher false-positive; opt-in via --pedantic


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    col: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.code} {self.message}"


def _str_const(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _significant_tokens(source: str) -> list[tokenize.TokenInfo]:
    """Source tokens with comments and layout noise stripped.

    Parenthesization is invisible to ``ast.parse`` (grouping parens are not in
    the tree), so WL005 recovers it from the token stream: with comments,
    newlines and indentation removed, a parenthesized operand sits directly
    between an ``(`` and ``)`` OP token. Token space -- rather than a raw
    character peek -- so a comment *inside* the parens no longer defeats the
    check (django/forms/models.py puts a ``# ForeignKey ...`` comment between
    the ``(`` and the and-chain). Returns an empty list if the source did not
    tokenize cleanly, in which case callers fall back to firing.
    """
    tokens: list[tokenize.TokenInfo] = []
    try:
        for tok in tokenize.generate_tokens(StringIO(source).readline):
            if tok.type not in _INSIGNIFICANT_TOKENS:
                tokens.append(tok)
    except tokenize.TokenError:
        return []
    return tokens


# Token types that carry no syntactic weight between a paren and its operand:
# comments and layout noise. Dropping them lets a paren-adjacency check ignore
# whatever the author put *visually* between a ``(`` and its expression.
_INSIGNIFICANT_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
)


# Actions that store no useful attribute on the namespace.
_NO_DEST_ACTIONS = {"help", "version"}


def _argparse_dest(call: ast.Call) -> tuple[str, str] | None:
    """Compute ``(dest, label)`` for an ``add_argument`` call, or ``None``.

    Mirrors argparse's own dest derivation: an explicit ``dest=`` wins; else the
    first long option (``--foo-bar`` -> ``foo_bar``), else the first short option
    (``-f`` -> ``f``), else the positional name. Returns ``None`` when the dest
    cannot be determined statically (dynamic ``dest=``/``argparse.SUPPRESS``, a
    ``help``/``version`` action that stores nothing, or no string option given).
    """
    dest: str | None = None
    dest_kw_seen = False
    action: str | None = None
    for kw in call.keywords:
        if kw.arg == "dest":
            dest_kw_seen = True
            dest = _str_const(kw.value)
        elif kw.arg == "action":
            action = _str_const(kw.value)
    if action in _NO_DEST_ACTIONS:
        return None
    if dest_kw_seen and dest is None:
        return None  # dest is dynamic or argparse.SUPPRESS — cannot reason

    long_opt = short_opt = positional = None
    for arg in call.args:
        s = _str_const(arg)
        if s is None:
            continue
        if s.startswith("--"):
            long_opt = long_opt or s
        elif s.startswith("-") and len(s) > 1:
            short_opt = short_opt or s
        else:
            positional = positional or s

    if dest is None:
        if long_opt is not None:
            dest, label = long_opt[2:].replace("-", "_"), long_opt
        elif short_opt is not None:
            dest, label = short_opt[1:].replace("-", "_"), short_opt
        elif positional is not None:
            dest, label = positional.replace("-", "_"), positional
        else:
            return None
    else:
        label = long_opt or short_opt or positional or dest

    if not dest.isidentifier():
        return None
    return dest, label


# --------------------------------------------------------------------------- #
# WL001 — replace-to-empty used as a prefix/suffix strip
# Origin: nephila/giturlparse PR #149 (superseded by merged #152)
# Provenance: fix merged in #152 (cf249252ed5); bug = .replace(group, "") as a strip.
# --------------------------------------------------------------------------- #
class ReplaceToEmptyPrefix:
    """``x.replace(P, "")`` guarded by ``x.startswith(P)`` / ``x.endswith(P)``.

    ``str.replace`` removes *every* occurrence, so a value that contains the
    marker twice is silently corrupted (``"/blob/x/blob/y" -> "x/y"``). The
    author meant ``str.removeprefix`` / ``str.removesuffix``. Narrow by design:
    fires only when the *same receiver* is guarded by the *same* literal.
    """

    code = "WL001"
    name = "replace-to-empty-prefix"
    tier = DEFAULT

    @staticmethod
    def _guard(test: ast.expr) -> tuple[str, str, str] | None:
        if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute)):
            return None
        method = test.func.attr
        if method not in ("startswith", "endswith"):
            return None
        if len(test.args) != 1 or test.keywords:
            return None
        literal = _str_const(test.args[0])
        if literal is None:
            return None
        suggestion = "removeprefix" if method == "startswith" else "removesuffix"
        return ast.unparse(test.func.value), literal, suggestion

    @staticmethod
    def _is_replace_to_empty(node: ast.Call, receiver_src: str, literal: str) -> bool:
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "replace"):
            return False
        if len(node.args) != 2 or node.keywords:
            return False
        if _str_const(node.args[0]) != literal or _str_const(node.args[1]) != "":
            return False
        return ast.unparse(node.func.value) == receiver_src

    def check(
        self, tree: ast.AST, path: str, source: str | None = None
    ) -> list[Finding]:
        out: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            guard = self._guard(node.test)
            if guard is None:
                continue
            receiver_src, literal, suggestion = guard
            # Only ``node.body`` runs while the guard holds. An ``elif``/``else``
            # branch (``node.orelse``) runs when the guard is *false*, so a
            # ``.replace`` there is not the "guarded strip that drops every
            # occurrence" this rule targets -- flagging it was a false positive.
            # Walk the body subtree only; nested control flow inside the body is
            # still reached under the guard.
            for stmt in node.body:
                for inner in ast.walk(stmt):
                    if isinstance(inner, ast.Call) and self._is_replace_to_empty(
                        inner, receiver_src, literal
                    ):
                        out.append(
                            Finding(
                                path,
                                inner.lineno,
                                inner.col_offset,
                                self.code,
                                f'.replace({literal!r}, "") guarded by '
                                f"{'startswith' if suggestion == 'removeprefix' else 'endswith'}"
                                f"({literal!r}) removes every occurrence; "
                                f"use str.{suggestion}({literal!r})",
                            )
                        )
        return out


# --------------------------------------------------------------------------- #
# WL002 — str.split(' ') instead of str.split()
# Origin: derek73/python-nameparser PR #164
# Provenance: fix merged in #164 (5c1954718cd); bug = .split(' ').
# --------------------------------------------------------------------------- #
class SplitSingleSpace:
    """``s.split(' ')`` where ``s.split()`` was almost certainly meant.

    ``"a  b ".split(' ')`` -> ``['a', '', 'b', '']`` keeps empty tokens and does
    not collapse runs or trim ends, while ``.split()`` does both. The single
    blanks then leak downstream (``['']`` where ``[]`` was expected, a leading
    space on a field). Only an *exact single space* literal fires — ``'  '`` or
    ``','`` are treated as deliberate delimiters and left alone.
    """

    code = "WL002"
    name = "split-single-space"
    tier = PEDANTIC

    def check(
        self, tree: ast.AST, path: str, source: str | None = None
    ) -> list[Finding]:
        out: list[Finding] = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ):
                continue
            if node.func.attr not in ("split", "rsplit"):
                continue
            if not node.args:
                continue
            if _str_const(node.args[0]) != " ":
                continue
            out.append(
                Finding(
                    path,
                    node.lineno,
                    node.col_offset,
                    self.code,
                    f".{node.func.attr}(' ') keeps empty tokens and will not "
                    "collapse/trim whitespace; use "
                    f".{node.func.attr}() unless single-space splitting is intended",
                )
            )
        return out


# --------------------------------------------------------------------------- #
# WL003 — deep negative index without a length guard  (PEDANTIC)
# Origin: savoirfairelinux/num2words PR #661
# Provenance: PR #661 open; bug on master (07814cb11415) = ordinal [-2] IndexError.
# --------------------------------------------------------------------------- #
class NegativeIndexNoGuard:
    """``x[-k]`` with ``k >= 2`` — IndexError if the sequence is shorter than k.

    The num2words bug indexed ``number_str[-2]`` unconditionally; ``"0"`` has
    length 1 and crashed. Pedantic because ``x[-2]`` is frequently safe (the
    length is known from context the checker cannot see), so this is opt-in.
    """

    code = "WL003"
    name = "negative-index-no-guard"
    tier = PEDANTIC

    def check(
        self, tree: ast.AST, path: str, source: str | None = None
    ) -> list[Finding]:
        out: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            idx = node.slice
            if (
                isinstance(idx, ast.UnaryOp)
                and isinstance(idx.op, ast.USub)
                and isinstance(idx.operand, ast.Constant)
                and isinstance(idx.operand.value, int)
                and idx.operand.value >= 2
            ):
                target = ast.unparse(node.value)
                out.append(
                    Finding(
                        path,
                        node.lineno,
                        node.col_offset,
                        self.code,
                        f"{target}[-{idx.operand.value}] raises IndexError if "
                        f"len({target}) < {idx.operand.value}; add a length guard",
                    )
                )
        return out


# --------------------------------------------------------------------------- #
# WL004 — argparse option defined but never wired (its dest is never read)
# Origin: un33k/python-slugify PR #180 (closed as duplicate of #176)
# Provenance: bug on master (7b6d5d96c19) = regex_pattern dest dropped by slugify_params(); fix PR #176 open.
# --------------------------------------------------------------------------- #
class ArgparseDeadDest:
    """An ``add_argument`` whose ``dest`` is never read — the flag is dropped.

    The slugify CLI defined ``--regex-pattern`` but ``slugify_params`` forwarded
    every namespace field *except* ``args.regex_pattern``, so the flag parsed and
    then silently vanished. Distilled to: a dest that no attribute access in the
    file ever reads, while *sibling* dests on the same parser are read — which is
    what proves the consumption site is this file and the gap is an oversight,
    not consumption happening elsewhere.

    Conservative by construction (favours false negatives):

    * Requires at least one collected dest to be read here; otherwise the whole
      file is treated as a parse-only site (consumption is elsewhere) and stays
      silent.
    * Bails entirely on any by-string / dynamic namespace access — ``vars()``,
      ``getattr``/``setattr``/``hasattr``, ``.__dict__`` or ``parse_known_args``
      — since a dest could be consumed without a literal ``.dest`` attribute.
    * A dest whose token coincides with any attribute read anywhere (even on an
      unrelated object) is assumed wired and left alone.
    """

    code = "WL004"
    name = "argparse-dead-dest"
    tier = DEFAULT

    @staticmethod
    def _anno_is_namespace(anno: ast.expr) -> bool:
        return ast.unparse(anno) in ("argparse.Namespace", "Namespace")

    @staticmethod
    def _dynamic_namespace_access(node: ast.AST, ns_names: set[str]) -> bool:
        """A by-string read of a namespace, hiding which dests are consumed."""
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "__dict__"
            and isinstance(node.value, ast.Name)
            and node.value.id in ns_names
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("vars", "getattr", "setattr", "hasattr")
        ):
            return any(isinstance(a, ast.Name) and a.id in ns_names for a in node.args)
        return False

    def check(
        self, tree: ast.AST, path: str, source: str | None = None
    ) -> list[Finding]:
        add_calls: list[tuple[str, str, int, int]] = []
        ns_names: set[str] = set()  # variables holding an argparse Namespace
        alias_sources: dict[str, set[str]] = {}  # `alias = name` edges (Name->Name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                # A namespace flows in from `x = ....parse_args(...)` ...
                if (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "parse_args"
                ):
                    ns_names.update(
                        t.id for t in node.targets if isinstance(t, ast.Name)
                    )
                # ... or through a plain alias `alias = name` (resolved against
                # ns_names after the walk), so a dest read via the alias counts
                # and a consumed flag isn't reported dead.
                elif isinstance(node.value, ast.Name):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            alias_sources.setdefault(t.id, set()).add(node.value.id)
            # ... or from a parameter annotated `argparse.Namespace`.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs):
                    if arg.annotation is not None and self._anno_is_namespace(
                        arg.annotation
                    ):
                        ns_names.add(arg.arg)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr == "parse_known_args":
                    return []  # tuple result — can't track which name is the namespace
                if attr == "add_argument" and node.args:
                    dest = _argparse_dest(node)
                    if dest is not None:
                        add_calls.append(
                            (dest[0], dest[1], node.lineno, node.col_offset)
                        )

        # Propagate aliases: a name reachable from a known namespace through
        # `alias = X` edges is another handle on it, so `alias.dest` counts as a
        # real read. Fixpoint covers chains (`cfg = ns; ns = args`). Conservative
        # -- reassigning a namespace name to a non-namespace is not unwound
        # (WL004 favours false negatives over false positives).
        prev = -1
        while len(ns_names) != prev:
            prev = len(ns_names)
            for tgt, srcs in alias_sources.items():
                if tgt not in ns_names and srcs & ns_names:
                    ns_names.add(tgt)

        # No locally-bound namespace -> this is a parse-only / definitions file;
        # the dests are consumed elsewhere and cannot be judged here.
        if not add_calls or not ns_names:
            return []

        ns_attrs: set[str] = set()  # attributes read on a namespace variable
        for node in ast.walk(tree):
            if self._dynamic_namespace_access(node, ns_names):
                return []
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in ns_names
            ):
                ns_attrs.add(node.attr)

        collected = {d for d, _, _, _ in add_calls}
        if not (collected & ns_attrs):
            return []  # no dest wired here -> consumption is in another file

        out: list[Finding] = []
        seen: set[str] = set()
        for dest, label, line, col in add_calls:
            if dest in ns_attrs or dest in seen:
                continue
            seen.add(dest)
            out.append(
                Finding(
                    path,
                    line,
                    col,
                    self.code,
                    f"argparse option {label!r} (dest {dest!r}) is parsed but its "
                    "value is never read; the flag is silently ignored",
                )
            )
        return out


# --------------------------------------------------------------------------- #
# WL005 — `not A and B or C` precedence (and binds tighter than or)
# Origin: alexanderlukanin13/coolname PR #34
# Provenance: PR #34 open; bug on master (7f895eed330e) = __nocheck precedence let _check_not_hanging run.
# --------------------------------------------------------------------------- #
class NotAndInOr:
    """Advisory: ``not A and B or C`` -- ``and`` binds tighter than ``or``, so
    the leading ``not A and`` guards only ``B``, not the trailing ``or``
    branches.

    Flags *precedence ambiguity* for human review, not a definite bug: Python
    parses the form as ``(not A and B) or C``, and the author either meant
    ``not A and (B or C)`` or has already disambiguated with parens (which this
    rule recognizes and suppresses). In coolname #34 the ambiguity bit for real:
    ``__nocheck`` failed to suppress ``_check_not_hanging()`` because the
    ``or check_prefix or max_slug_length`` branches escaped the guard. Most
    real-world hits are legitimate conditions worth a glance, not defects --
    hence pedantic and opt-in.

    Narrow: fires only when an ``and``-chain containing a ``not`` is a direct
    operand of an ``or``-chain and is not wrapped in disambiguating parens.
    """

    code = "WL005"
    name = "not-and-in-or-precedence"
    tier = PEDANTIC

    @staticmethod
    def _and_chain_has_not(node: ast.BoolOp) -> bool:
        return isinstance(node.op, ast.And) and any(
            isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.Not)
            for v in node.values
        )

    @staticmethod
    def _chain_is_parenthesized(
        node: ast.expr, tokens: list[tokenize.TokenInfo]
    ) -> bool:
        """Whether ``node``'s source span is wrapped in a matching ``(...)`` pair.

        ``ast.parse`` discards grouping parentheses, so ``(not a and b) or c``
        and the unparenthesized bug parse to the *same* tree. Wrapping parens
        signal "I scoped this on purpose", at which point the precedence the
        rule warns about is no longer ambiguous, so we suppress.

        Working in token space (comments/layout already stripped by
        ``_significant_tokens``), find the node's first and last significant
        tokens and check the ones immediately around them: if they are ``(`` and
        ``)``, the node is parenthesized. Token space -- not raw characters --
        so a comment *inside* the parens (``(\\n # why\\n not a and b\\n)``) no
        longer defeats the check, the gap that left a real false positive in
        django/forms/models.py. Only a pair wrapping *this* node suppresses:
        ``(not a) and b`` scopes the ``not`` to ``a`` alone and the trailing
        ``or`` still escapes, so it stays a real finding.
        """
        if node.end_lineno is None or node.end_col_offset is None:
            return False  # parsed without end-position metadata (pre-3.8 mode)
        start = (node.lineno, node.col_offset)
        end = (node.end_lineno, node.end_col_offset)
        first = last = None
        for idx, tok in enumerate(tokens):
            if first is None and tok.start == start:
                first = idx
            if tok.end == end and first is not None:
                last = idx
                break
        if first is None or last is None:
            return False
        left = tokens[first - 1] if first > 0 else None
        right = tokens[last + 1] if last + 1 < len(tokens) else None
        return (
            left is not None
            and left.type == tokenize.OP
            and left.string == "("
            and right is not None
            and right.type == tokenize.OP
            and right.string == ")"
        )

    def check(
        self, tree: ast.AST, path: str, source: str | None = None
    ) -> list[Finding]:
        out: list[Finding] = []
        tokens = _significant_tokens(source) if source is not None else None
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
                continue
            for val in node.values:
                if isinstance(val, ast.BoolOp) and self._and_chain_has_not(val):
                    # ``(not a and b) or c`` parses identically to the
                    # unparenthesized bug -- ast drops the grouping parens. If
                    # the and-chain is wrapped in source, the author
                    # disambiguated and the precedence is no longer ambiguous,
                    # so suppress (see _chain_is_parenthesized).
                    if tokens is not None and self._chain_is_parenthesized(val, tokens):
                        continue
                    out.append(
                        Finding(
                            path,
                            val.lineno,
                            val.col_offset,
                            self.code,
                            "advisory: `not A and B or C` -- `and` binds tighter "
                            "than `or`, so the leading `not A and` guards only B, "
                            "not the trailing `or` branches; review whether the "
                            "guard should cover all (write `not A and (B or C)`) "
                            "-- most hits are legitimate (coolname #34).",
                        )
                    )
                    break  # one finding per `or` chain
        return out


CHECKERS = [
    ReplaceToEmptyPrefix(),
    SplitSingleSpace(),
    NegativeIndexNoGuard(),
    ArgparseDeadDest(),
    NotAndInOr(),
]


def select_checkers(*, pedantic: bool = False, codes: set[str] | None = None) -> list:
    """Return the active checkers.

    ``pedantic`` includes the opt-in tier. ``codes`` (e.g. ``{"WL001"}``)
    restricts to those rules and, when given, overrides the tier filter.
    """
    if codes is not None:
        return [c for c in CHECKERS if c.code in codes]
    return [c for c in CHECKERS if c.tier == DEFAULT or pedantic]


def check_source(
    source: str,
    path: str = "<unknown>",
    *,
    pedantic: bool = False,
    codes: set[str] | None = None,
) -> list[Finding]:
    """Run the selected checkers over one source string; sorted findings."""
    tree = ast.parse(source)
    findings: list[Finding] = []
    for checker in select_checkers(pedantic=pedantic, codes=codes):
        findings.extend(checker.check(tree, path, source))
    findings.sort(key=lambda f: (f.line, f.col, f.code))
    return findings


# Bug classes considered but NOT shipped — each would only fire with an
# unacceptable false-positive rate as a purely-static rule. Kept here so the
# reasoning is not lost and a future, smarter implementation can revisit.
NON_GENERALIZED = {
    "break-vs-continue": "jkwill87/mnamer #371 — whether `break` should be "
    "`continue` is entirely loop-intent dependent; both are usually correct.",
    "sign-doubling": "python-humanize/humanize #326 — negative whole+fraction "
    "double-sign is a numeric-formatting specific, not a syntactic, pattern.",
    "validation-branch-order": "python-validators/validators #463 — the unsafe "
    "ordering of `,` vs `-`/`/` handling is specific to that parser's structure.",
    "radix-from-ignored-param": "skorokithakis/shortuuid #115 — requires reading "
    "the docstring contract ('alphabet is ignored') and matching it to impl.",
    "uri-fragment-as-userinfo": "go-openapi/strfmt #269 (merged) — a URI "
    "validator rejected absolute URIs with a fragment ('https://host#@frag') "
    "because Go's url.ParseRequestURI assumes a request-line with no fragment, "
    "so it misread '#@frag' as invalid userinfo. This is a real bug but it is "
    "Go-specific: every Python URI parser (urllib.parse, rfc3986, yarl, furl, "
    "hyperlink — probed 2026-06-24) is RFC-3986-compliant and correctly treats "
    "'#' as the fragment delimiter. No Python surface bites, so there is no "
    "property template to ship — the class does not exist outside Go's "
    "request-URI contract. A static AST rule is similarly impossible.",
    "rng-from-unordered-set": "Iterating a set into a population for random "
    "selection — random.choice/sample/choices over set-ordered data, or "
    "list(some_set) feeding random.choices weights — is non-deterministic across "
    "processes: PYTHONHASHSEED varies per worker, so set iteration order (and "
    "thus item<->weight alignment) changes run to run. The bare surface form "
    "(random.choice({1,2,3})) is rare and a narrow rule could catch it, but the "
    "real class (set->list->positional use, e.g. the EvoEcos f982904 fix) is only "
    "visible cross-process and is best caught by a reproducibility property test "
    "(run twice under differing PYTHONHASHSEED, assert identical output), not a "
    "static rule. No public gift-PR origin to verify against, so not shipped.",
}
