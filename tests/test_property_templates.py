"""Tests for the property-test templates.

The positive case is a *faithful reproduction* of the real rollover bug shipped
in millify#13 / numerize#17 / si-prefix#17: pick the unit from the unrounded
value, then round the mantissa — so a value just under a boundary rounds up to
``base`` while keeping the smaller unit. The negative case carries correctly.
"""

from __future__ import annotations

import datetime
import math

from wildlint.property_templates import (
    DATE_KWARGS,
    ROLLOVER,
    TEMPLATES,
    find_date_kwargs,
    find_rollover,
    get_template,
)

_SI = ["", "k", "M", "G", "T", "P", "E", "Z", "Y"]


def buggy_humanize(n: float, precision: int = 1) -> str:
    """Reproduces the real bug: unit chosen *before* the mantissa is rounded.

    Mirrors millify/numerize/si-prefix — ``millify(999999)`` -> ``'1000.0k'``.
    """
    if n == 0:
        return "0"
    sign = "-" if n < 0 else ""
    n = abs(n)
    idx = min(int(math.log10(n) // 3), len(_SI) - 1)
    mantissa = n / (1000**idx)
    return f"{sign}{round(mantissa, precision)}{_SI[idx]}"


def correct_humanize(n: float, precision: int = 1) -> str:
    """The fix: after rounding, carry into the next unit if it hit ``base``."""
    if n == 0:
        return "0"
    sign = "-" if n < 0 else ""
    n = abs(n)
    idx = min(int(math.log10(n) // 3), len(_SI) - 1)
    mantissa = round(n / (1000**idx), precision)
    if mantissa >= 1000 and idx < len(_SI) - 1:
        idx += 1
        mantissa = round(n / (1000**idx), precision)
    return f"{sign}{mantissa}{_SI[idx]}"


# --------------------------------------------------------------------------- #
# find_rollover — heuristic mode (no units table)
# --------------------------------------------------------------------------- #


def test_find_rollover_catches_the_real_bug():
    violations = find_rollover(buggy_humanize)
    assert violations, "should catch the rollover bug"
    # the canonical case must be among them
    assert any(abs(v.value) == 999999 for v in violations)


def test_find_rollover_silent_on_correct_humanizer():
    assert find_rollover(correct_humanize) == []


def test_find_rollover_silent_on_correct_humanizer_with_units():
    assert find_rollover(correct_humanize, units=_SI) == []


def test_find_rollover_units_mode_catches_bug():
    violations = find_rollover(buggy_humanize, units=_SI)
    assert violations
    assert all(abs(v.mantissa) >= 1000 for v in violations)


def test_find_rollover_top_unit_not_flagged():
    # A humanizer that legitimately exceeds base at the LARGEST unit (nothing
    # bigger to carry into) must not be flagged in units mode.
    def only_two_units(n: float) -> str:
        n = abs(n)
        if n < 1000:
            # round first, then carry into 'k' so 999.9999 -> '1k', not '1000'
            r = round(n)
            return "1k" if r >= 1000 else str(r)
        return f"{round(n / 1000)}k"  # 'k' is the top unit; big mantissa is fine

    assert find_rollover(only_two_units, units=["", "k"]) == []


def test_find_rollover_skips_crashing_inputs():
    def crashes_on_negatives(n: float) -> str:
        if n < 0:
            raise ValueError("no negatives")
        return correct_humanize(n)

    # must not raise, must stay silent (the correct path has no rollover)
    assert find_rollover(crashes_on_negatives) == []


def test_find_rollover_binary_base_1024():
    def buggy_bytes(n: float) -> str:
        units = ["B", "K", "M", "G", "T"]
        n = float(abs(n))
        idx = 0
        while n >= 1024 and idx < len(units) - 1:
            n /= 1024
            idx += 1
        # bug: round to int AFTER picking unit -> 1023.6 -> '1024K'
        return f"{round(n)}{units[idx]}"

    violations = find_rollover(buggy_bytes, base=1024.0)
    assert violations


def test_find_rollover_custom_values():
    calls = []

    def fn(n: float) -> str:
        calls.append(n)
        return "1.0k"

    find_rollover(fn, values=[1.0, 2.0, 3.0])
    assert calls == [1.0, 2.0, 3.0]


def test_find_rollover_ignores_non_magnitude_output():
    # A function returning prose, not a magnitude+unit, yields no violations.
    assert find_rollover(lambda _: "not a number") == []


# --------------------------------------------------------------------------- #
# Violation formatting
# --------------------------------------------------------------------------- #


def test_violation_str_is_actionable():
    v = find_rollover(buggy_humanize)[0]
    s = str(v)
    assert "rollover" in s
    assert "mantissa" in s


# --------------------------------------------------------------------------- #
# template registry + rendering
# --------------------------------------------------------------------------- #


def test_get_template_by_code_and_name():
    assert get_template("WP001") is ROLLOVER
    assert get_template("rounding-rollover") is ROLLOVER
    assert get_template("rollover") is ROLLOVER
    assert get_template("nope") is None


def test_render_produces_importable_pytest_module():
    rendered = ROLLOVER.render(func="millify", import_from="millify", base=1000)
    assert "from millify import millify" in rendered
    assert "find_rollover(millify, base=1000)" in rendered
    assert "def test_no_rounding_rollover():" in rendered
    # provenance is carried into the rendered file as a comment
    assert "millify#13" in rendered


def test_rendered_template_is_valid_python():
    import ast

    rendered = ROLLOVER.render(func="millify", import_from="millify")
    ast.parse(rendered)  # must not raise


def test_templates_registry_nonempty_and_well_formed():
    assert TEMPLATES
    for t in TEMPLATES:
        assert t.code.startswith("WP")
        assert t.provenance
        assert callable(t.check)


# --------------------------------------------------------------------------- #
# find_date_kwargs — date/datetime-subclass confusion (WP002, deepdiff#602)
# --------------------------------------------------------------------------- #


def buggy_truncate(value: object) -> object:
    """Reproduces deepdiff#602: assumes a datetime, calls
    ``.replace(second=0, microsecond=0)`` unconditionally. Crashes on a bare
    ``date`` because ``date.replace`` accepts only year/month/day."""
    return value.replace(second=0, microsecond=0)  # type: ignore[union-attr]


def safe_truncate(value: object) -> object:
    """The fix: only apply datetime-only ``.replace`` when the value actually
    carries time fields (``date`` has no ``hour``)."""
    if hasattr(value, "hour"):
        return value.replace(second=0, microsecond=0)  # type: ignore[union-attr]
    return value


def test_find_date_kwargs_catches_the_real_bug():
    violations = find_date_kwargs(buggy_truncate)
    assert violations, "should catch the date/datetime-subclass bug"
    # the bare-date probe (not a datetime) must be among the violations
    assert any(
        isinstance(v.value, datetime.date)
        and not isinstance(v.value, datetime.datetime)
        for v in violations
    )


def test_find_date_kwargs_silent_on_safe():
    assert find_date_kwargs(safe_truncate) == []


def test_find_date_kwargs_catches_attribute_error_path():
    # Reading .hour on a date (which has none) bites via AttributeError, and the
    # message cites the time-only field "hour" — a different exception type but
    # the same bug class.
    def reads_hour(value: object) -> object:
        return value.hour  # type: ignore[union-attr]

    violations = find_date_kwargs(reads_hour)
    assert violations
    assert any("hour" in v.output for v in violations)


def test_find_date_kwargs_skips_unrelated_crash():
    # A TypeError that does NOT cite a time-only field is a different bug class
    # and must not be recorded as a date-kwargs violation.
    def unrelated(value: object) -> object:
        if not isinstance(value, int):
            raise TypeError("argument must be int, not " + type(value).__name__)
        return value

    assert find_date_kwargs(unrelated) == []


def test_date_kwargs_violation_str_is_actionable():
    v = find_date_kwargs(buggy_truncate)[0]
    s = str(v)
    assert "date-kwargs" in s
    assert "TypeError" in s
    assert "second" in s  # the offending time-only field


def test_get_template_wp002():
    assert get_template("WP002") is DATE_KWARGS
    assert get_template("date-time-kwargs") is DATE_KWARGS
    assert get_template("nope") is None


def test_render_date_kwargs_module():
    rendered = DATE_KWARGS.render(func="truncate", import_from="deepdiff", base=1000)
    assert "from deepdiff import truncate" in rendered
    assert "find_date_kwargs(truncate)" in rendered
    assert "def test_does_not_crash_on_date():" in rendered
    assert "deepdiff#602" in rendered
    # base is accepted for CLI uniformity but the date-kwargs check has no base
    assert "base=" not in rendered.split("def test_does_not_crash_on_date")[1]


def test_rendered_date_kwargs_is_valid_python():
    import ast

    rendered = DATE_KWARGS.render(func="truncate", import_from="deepdiff")
    ast.parse(rendered)  # must not raise
