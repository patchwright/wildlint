"""Detector registry for wildlint.

Each checker is distilled from a *real* bug found in the wild (a public upstream
PR), generalized into the smallest static rule that still catches the class
without drowning the user in false positives. Checkers that could only be made
to fire with an unacceptable false-positive rate are documented in
``NON_GENERALIZED`` rather than shipped.

A checker is any object exposing ``code``, ``name``, ``tier`` and a
``check(tree, path) -> list[Finding]`` method. Register one by appending an
instance to ``CHECKERS``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

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


# --------------------------------------------------------------------------- #
# WL001 — replace-to-empty used as a prefix/suffix strip
# Origin: nephila/giturlparse PR #149
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

    def check(self, tree: ast.AST, path: str) -> list[Finding]:
        out: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            guard = self._guard(node.test)
            if guard is None:
                continue
            receiver_src, literal, suggestion = guard
            for inner in ast.walk(node):
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

    def check(self, tree: ast.AST, path: str) -> list[Finding]:
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

    def check(self, tree: ast.AST, path: str) -> list[Finding]:
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


CHECKERS = [
    ReplaceToEmptyPrefix(),
    SplitSingleSpace(),
    NegativeIndexNoGuard(),
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
        findings.extend(checker.check(tree, path))
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
