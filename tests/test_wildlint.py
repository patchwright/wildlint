"""Tests for wildlint detectors.

Positive cases mirror the real upstream bug each rule was distilled from;
negative cases are the legitimate code the rule must stay silent on.
"""

from __future__ import annotations

from wildlint.checkers import check_source

# --------------------------------------------------------------------------- #
# WL001 — replace-to-empty prefix/suffix (giturlparse #149)
# --------------------------------------------------------------------------- #


def _codes(src: str, **kw) -> list[str]:
    return [f.code for f in check_source(src, "t.py", **kw)]


def test_wl001_fires_on_startswith_replace_empty():
    src = (
        "def f(path):\n"
        "    if path.startswith('/blob/'):\n"
        "        return path.replace('/blob/', '')\n"
    )
    assert _codes(src) == ["WL001"]


def test_wl001_fires_on_endswith_suffix():
    src = (
        "def f(name):\n"
        "    if name.endswith('.py'):\n"
        "        return name.replace('.py', '')\n"
    )
    assert _codes(src) == ["WL001"]


def test_wl001_silent_when_replacement_not_empty():
    src = (
        "def f(p):\n"
        "    if p.startswith('/x/'):\n"
        "        return p.replace('/x/', '/y/')\n"
    )
    assert "WL001" not in _codes(src)


def test_wl001_silent_when_literals_differ():
    src = (
        "def f(p):\n    if p.startswith('/a/'):\n        return p.replace('/b/', '')\n"
    )
    assert "WL001" not in _codes(src)


def test_wl001_silent_without_guard():
    # No startswith/endswith guard -> not our pattern (could be intentional).
    assert "WL001" not in _codes("def f(p):\n    return p.replace('/x/', '')\n")


def test_wl001_silent_on_replace_in_else_branch():
    # The else branch (node.orelse) runs when the guard is *false*, so the
    # .replace there is not a guarded strip -- flagging it was a false positive.
    src = (
        "def f(p):\n"
        "    if p.startswith('/x/'):\n"
        "        return p\n"
        "    else:\n"
        "        return p.replace('/x/', '')\n"
    )
    assert "WL001" not in _codes(src)


def test_wl001_silent_on_replace_in_elif_branch():
    # elif is node.orelse; reached only when the startswith guard is false.
    src = (
        "def f(p):\n"
        "    if p.startswith('/x/'):\n"
        "        return p\n"
        "    elif p.startswith('/y/'):\n"
        "        return p.replace('/x/', '')\n"
    )
    assert "WL001" not in _codes(src)


def test_wl001_still_fires_on_replace_nested_in_body():
    # Nested control flow *inside* the guarded body is still reached under the
    # guard, so a matching .replace there must still fire.
    src = (
        "def f(p):\n"
        "    if p.startswith('/x/'):\n"
        "        for _ in range(3):\n"
        "            p.replace('/x/', '')\n"
    )
    assert _codes(src) == ["WL001"]


# --------------------------------------------------------------------------- #
# WL002 — split single space (nameparser #164)
# --------------------------------------------------------------------------- #


def test_wl002_off_by_default():
    # Demoted to pedantic in 0.1.1 — its FP rate on clean code is real.
    assert _codes("x = name.split(' ')\n") == []


def test_wl002_fires_on_split_single_space_when_pedantic():
    assert _codes("x = name.split(' ')\n", pedantic=True) == ["WL002"]


def test_wl002_fires_on_rsplit_single_space_when_pedantic():
    assert _codes("x = name.rsplit(' ')\n", pedantic=True) == ["WL002"]


def test_wl002_silent_on_bare_split():
    assert "WL002" not in _codes("x = name.split()\n", pedantic=True)


def test_wl002_silent_on_double_space():
    # Two spaces is a deliberate delimiter, not the bug.
    assert "WL002" not in _codes("x = name.split('  ')\n", pedantic=True)


def test_wl002_silent_on_comma():
    assert "WL002" not in _codes("x = name.split(',')\n", pedantic=True)


# --------------------------------------------------------------------------- #
# WL003 — deep negative index, PEDANTIC (num2words #661)
# --------------------------------------------------------------------------- #


def test_wl003_off_by_default():
    assert _codes("x = s[-2]\n") == []


def test_wl003_fires_when_pedantic():
    assert _codes("x = s[-2]\n", pedantic=True) == ["WL003"]


def test_wl003_silent_on_last_element():
    # x[-1] is the idiom for "last item" and never out of bounds on non-empty.
    assert _codes("x = s[-1]\n", pedantic=True) == []


def test_wl003_fires_on_deeper_index_when_pedantic():
    assert _codes("x = s[-3]\n", pedantic=True) == ["WL003"]


# --------------------------------------------------------------------------- #
# WL004 — argparse option defined but never wired (slugify #180)
# --------------------------------------------------------------------------- #

# Mirrors the slugify CLI shape: many flags wired, one (--regex-pattern) dropped.
_SLUGIFY_LIKE = (
    "import argparse\n"
    "def parse(argv):\n"
    "    p = argparse.ArgumentParser()\n"
    "    p.add_argument('text')\n"
    "    p.add_argument('--max-length', type=int)\n"
    "    p.add_argument('--no-entities', dest='entities', action='store_false')\n"
    "    p.add_argument('--regex-pattern')\n"
    "    args = p.parse_args(argv)\n"
    "    return dict(text=args.text, max_length=args.max_length, "
    "entities=args.entities)\n"
)


def test_wl004_fires_on_unwired_option():
    out = check_source(_SLUGIFY_LIKE, "cli.py")
    assert [f.code for f in out] == ["WL004"]
    assert "regex_pattern" in out[0].message


def test_wl004_default_tier():
    # WL004 is low-FP and runs without --pedantic.
    assert "WL004" in _codes(_SLUGIFY_LIKE)


def test_wl004_silent_when_flag_is_read():
    src = _SLUGIFY_LIKE.replace(
        "entities=args.entities)", "entities=args.entities, rp=args.regex_pattern)"
    )
    assert "WL004" not in _codes(src)


def test_wl004_silent_when_no_dest_read_in_file():
    # Parse-only site: consumption happens in another module -> stay silent.
    src = (
        "import argparse\n"
        "def build():\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--regex-pattern')\n"
        "    p.add_argument('--max-length')\n"
        "    return p.parse_args()\n"
    )
    assert "WL004" not in _codes(src)


def test_wl004_silent_with_vars_namespace():
    src = (
        "import argparse\n"
        "def run(argv):\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--text')\n"
        "    p.add_argument('--regex-pattern')\n"
        "    args = p.parse_args(argv)\n"
        "    return go(text=args.text, **{k: v for k, v in vars(args).items()})\n"
    )
    assert "WL004" not in _codes(src)


def test_wl004_silent_with_getattr_namespace():
    src = (
        "import argparse\n"
        "def run(argv):\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--text')\n"
        "    p.add_argument('--regex-pattern')\n"
        "    args = p.parse_args(argv)\n"
        "    return (args.text, getattr(args, 'regex_pattern'))\n"
    )
    assert "WL004" not in _codes(src)


def test_wl004_silent_with_parse_known_args():
    src = (
        "import argparse\n"
        "def run(argv):\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--text')\n"
        "    p.add_argument('--regex-pattern')\n"
        "    args, rest = p.parse_known_args(argv)\n"
        "    return args.text\n"
    )
    assert "WL004" not in _codes(src)


def test_wl004_skips_version_and_help_actions():
    # action='version'/'help' store no dest -> never reported as dead.
    src = (
        "import argparse\n"
        "def run(argv):\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--text')\n"
        "    p.add_argument('--version', action='version', version='1')\n"
        "    args = p.parse_args(argv)\n"
        "    return args.text\n"
    )
    assert "WL004" not in _codes(src)


def test_wl004_silent_when_all_wired():
    src = (
        "import argparse\n"
        "def run(argv):\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--text')\n"
        "    p.add_argument('--count', type=int)\n"
        "    args = p.parse_args(argv)\n"
        "    return (args.text, args.count)\n"
    )
    assert "WL004" not in _codes(src)


# --------------------------------------------------------------------------- #
# selection / tier behavior
# --------------------------------------------------------------------------- #


def test_default_tier_is_wl001_only():
    # After the 0.1.1 demotion, only WL001 runs by default.
    src = "a = name.split(' ')\nif p.startswith('/x/'):\n    p = p.replace('/x/', '')\n"
    assert _codes(src) == ["WL001"]
    assert sorted(_codes(src, pedantic=True)) == ["WL001", "WL002"]


def test_select_restricts_to_codes():
    src = "a = name.split(' ')\nif p.startswith('/x/'):\n    p = p.replace('/x/', '')\n"
    assert _codes(src, codes={"WL002"}) == ["WL002"]


def test_select_can_pick_pedantic_rule_without_flag():
    # Explicit --select overrides the tier filter.
    assert _codes("x = s[-2]\n", codes={"WL003"}) == ["WL003"]


def test_clean_source_has_no_findings():
    src = "def f(p):\n    return p.removeprefix('/x/').split()\n"
    assert check_source(src, "t.py", pedantic=True) == []


def test_syntax_error_does_not_crash_check_source():
    import pytest

    with pytest.raises(SyntaxError):
        check_source("def (:\n", "t.py")


# --------------------------------------------------------------------------- #
# WL005 — `not A and B or C` precedence (coolname #34)
# --------------------------------------------------------------------------- #
def test_wl005_fires_on_not_and_in_or():
    # the coolname #34 shape: not X and Y or Z or W
    src = "if not a and b or c or d:\n    pass\n"
    assert _codes(src, pedantic=True) == ["WL005"]


def test_wl005_coolname_origin_shape():
    # mirrors coolname #34: not config.get(...) and self.a or self.b or self.c
    src = "if not cfg.get('x') and self.a or self.b or self.c:\n    pass\n"
    assert "WL005" in _codes(src, pedantic=True)


def test_wl005_silent_when_parenthesized():
    # the fix: not X and (Y or Z) -- the `or` is now inside the `and`
    src = "if not a and (b or c or d):\n    pass\n"
    assert "WL005" not in _codes(src, pedantic=True)


def test_wl005_not_in_default_tier():
    src = "if not a and b or c:\n    pass\n"
    assert "WL005" not in _codes(src)  # default tier must not run WL005


def test_wl005_silent_when_no_not_in_and_chain():
    src = "if a and b or c:\n    pass\n"
    assert "WL005" not in _codes(src, pedantic=True)


def test_wl005_silent_when_and_chain_is_parenthesized():
    # The v0.5.2 false positive: parens around the and-chain ITSELF (not moving
    # the `or` inside the `and`) parse to the SAME tree as the unparenthesized
    # bug -- ast.parse drops grouping parens. The checker must peek the source to
    # tell "author disambiguated" from "author forgot precedence".
    src = "if (not a and b) or c:\n    pass\n"
    assert _codes(src, pedantic=True) == []


def test_wl005_silent_when_and_chain_double_parenthesized():
    src = "if ((not a and b)) or c:\n    pass\n"
    assert _codes(src, pedantic=True) == []


def test_wl005_silent_when_and_chain_wrapped_across_lines():
    # The paren peek must use absolute offsets so a multi-line wrap counts --
    # this is the shape of the real-world django hits in the v0.5.2 review.
    src = "if (\n    not a and b\n) or c:\n    pass\n"
    assert _codes(src, pedantic=True) == []


def test_wl005_still_fires_when_not_scopes_only_one_operand():
    # (not a) and b or c: the `not` scopes only `a`, so the trailing `or c`
    # still escapes the leading guard -- parens here do NOT wrap the and-chain,
    # so the precedence hazard is real and must still fire.
    src = "if (not a) and b or c:\n    pass\n"
    assert _codes(src, pedantic=True) == ["WL005"]


def test_wl005_still_fires_on_unparenthesized_coolname_shape():
    # Sanity: the real coolname #34 bug (no disambiguating parens) still fires.
    src = "if not cfg.get('x') and self.a or self.b or self.c:\n    pass\n"
    assert _codes(src, pedantic=True) == ["WL005"]


def test_wl005_whole_expr_parens_do_not_suppress():
    # (not a and b or c) wraps the WHOLE or-expr, not the and-chain -- the
    # precedence ambiguity inside is unchanged, so it still fires.
    src = "if (not a and b or c):\n    pass\n"
    assert _codes(src, pedantic=True) == ["WL005"]
