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
        "def f(p):\n"
        "    if p.startswith('/a/'):\n"
        "        return p.replace('/b/', '')\n"
    )
    assert "WL001" not in _codes(src)


def test_wl001_silent_without_guard():
    # No startswith/endswith guard -> not our pattern (could be intentional).
    assert "WL001" not in _codes("def f(p):\n    return p.replace('/x/', '')\n")


# --------------------------------------------------------------------------- #
# WL002 — split single space (nameparser #164)
# --------------------------------------------------------------------------- #


def test_wl002_fires_on_split_single_space():
    assert _codes("x = name.split(' ')\n") == ["WL002"]


def test_wl002_fires_on_rsplit_single_space():
    assert _codes("x = name.rsplit(' ')\n") == ["WL002"]


def test_wl002_silent_on_bare_split():
    assert "WL002" not in _codes("x = name.split()\n")


def test_wl002_silent_on_double_space():
    # Two spaces is a deliberate delimiter, not the bug.
    assert "WL002" not in _codes("x = name.split('  ')\n")


def test_wl002_silent_on_comma():
    assert "WL002" not in _codes("x = name.split(',')\n")


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
# selection / tier behavior
# --------------------------------------------------------------------------- #


def test_select_restricts_to_codes():
    src = "a = name.split(' ')\nif p.startswith('/x/'):\n    p = p.replace('/x/', '')\n"
    assert _codes(src) == ["WL001", "WL002"] or _codes(src) == ["WL002", "WL001"]
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
