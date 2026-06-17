"""Property-test templates for wildlint.

Some bug classes resist a low-false-positive *static* rule because the defect is
semantic, not syntactic — the same wrong behaviour is reached by different code
each time. The recurring **rounding-rollover** bug in number / byte / SI-prefix
humanizers is the archetype: ``boltons#403``, ``millify#13``, ``numerize#17`` and
``si-prefix#17`` are four distinct implementations of *one* invariant break, and
none of them has a stable AST signature (one is ``<=`` vs ``<``, another is a
missing carry after rounding, another rounds an unrounded boundary value). A
static rule that caught all four would also flag mountains of correct code.

What they share is a falsifiable *property*: a humanizer must never emit a
mantissa ``>= base`` while a larger unit is still available. ``millify(999999)``
must render as ``'1M'``, never ``'1000k'``. That is trivially checked by a
property test.

This module ships that check two ways:

* :func:`find_rollover` — a **dependency-free** runtime checker that sweeps the
  dangerous boundary inputs (values that round *up* across a unit boundary) and
  returns the concrete violations. Usable directly in a maintainer's test suite
  or in CI.
* :class:`PropertyTemplate` / :data:`TEMPLATES` — a renderable pytest template a
  maintainer can paste into their own project (``wildlint --template rollover``).

The design mirrors ``checkers.py``: a small registry of objects with ``code`` /
``name`` / ``tier``, each distilled from real upstream bugs.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

DEFAULT = "default"

# Leading signed number, optional decimals, then (after optional space) the unit.
_MANTISSA_RE = re.compile(r"\s*([+-]?\d+(?:\.\d+)?)\s*(.*?)\s*$")


@dataclass(frozen=True)
class Violation:
    """One input whose humanized output broke the rollover invariant."""

    value: float
    output: str
    mantissa: float
    unit: str
    reason: str

    def __str__(self) -> str:
        return (
            f"rollover: f({self.value!r}) -> {self.output!r} "
            f"(mantissa {self.mantissa:g} >= base with unit {self.unit!r}); "
            f"{self.reason}"
        )


def _parse_mantissa_unit(s: str) -> tuple[float | None, str] | None:
    """Split a humanized string into ``(mantissa, unit)``.

    ``'1000.0k'`` -> ``(1000.0, 'k')``; ``'1.0 M'`` -> ``(1.0, 'M')``;
    ``'1024B'`` -> ``(1024.0, 'B')``. Returns ``None`` if no leading number is
    present (the string is not a magnitude-and-unit form this check understands).
    """
    m = _MANTISSA_RE.match(s)
    if m is None:
        return None
    try:
        return float(m.group(1)), m.group(2).strip()
    except ValueError:
        return None


def _boundary_values(base: float, max_exponent: int) -> list[float]:
    """Inputs that sit *just below* each unit boundary and round up across it.

    The rollover bug only shows near ``base**k``: a value whose mantissa rounds
    from ``~base - epsilon`` up to ``base`` at the smaller unit. We sweep, for
    each boundary, the exact power, its integer neighbours, and a ladder of
    "nines" fractions covering rounding at precisions 1..8 — in both signs and as
    both ``int`` and ``float`` (some humanizers special-case integers).
    """
    fracs = (0.9, 0.99, 0.999, 0.9999, 0.99999, 0.999999, 0.9999999, 0.99999999)
    out: list[float] = []
    for k in range(1, max_exponent + 1):
        b = base**k
        candidates = [b, b - 1, b + 1, *(b * f for f in fracs)]
        for c in candidates:
            for sign in (1.0, -1.0):
                out.append(sign * float(c))
                ic = int(round(c))
                if ic > 0:
                    out.append(sign * ic)
    # de-duplicate, preserve order
    return list(dict.fromkeys(out))


def find_rollover(
    fn: Callable[[float], str],
    *,
    base: float = 1000.0,
    max_exponent: int = 8,
    units: Sequence[str] | None = None,
    values: Iterable[float] | None = None,
    parse: Callable[[str], tuple[float | None, str] | None] | None = None,
) -> list[Violation]:
    """Sweep boundary inputs and return every rounding-rollover violation.

    ``fn`` is the humanizer under test (``int|float -> str``). ``base`` is the
    radix between units (1000 for SI/metric, 1024 for binary bytes).

    If ``units`` (ordered small→large) is given, the check is exact: a mantissa
    ``>= base`` is a violation unless the rendered unit is the largest one (past
    the table, no larger unit exists, so a big mantissa is legitimate). Without
    ``units`` a heuristic is used: flag mantissas in ``[base, base*base)`` — the
    rollover signature is a mantissa that rounded from just under ``base`` to
    ``base`` (≈ 1000.0), never an astronomically large one.

    ``values`` overrides the default boundary sweep; ``parse`` overrides the
    default ``(mantissa, unit)`` extractor. Inputs that make ``fn`` raise are
    skipped (a crash is a different bug class than a rollover).
    """
    parse = parse or _parse_mantissa_unit
    sweep = list(values) if values is not None else _boundary_values(base, max_exponent)
    top_unit = units[-1].strip() if units else None

    seen: set[tuple[float, str]] = set()
    violations: list[Violation] = []
    for v in sweep:
        try:
            out = fn(v)
        except Exception:
            continue
        if not isinstance(out, str):
            continue
        parsed = parse(out)
        if parsed is None:
            continue
        mantissa, unit = parsed
        if mantissa is None:
            continue
        amant = abs(mantissa)

        if top_unit is not None:
            is_violation = amant >= base and unit != top_unit
            reason = "a larger unit was available but was not used"
        else:
            is_violation = base <= amant < base * base
            reason = (
                "mantissa landed in [base, base*base); a larger unit should "
                "have been chosen (pass units= for an exact check)"
            )

        if is_violation:
            key = (mantissa, unit)
            if key not in seen:
                seen.add(key)
                violations.append(Violation(v, out, mantissa, unit, reason))
    return violations


_RENDERED = """\
# Rounding-rollover property test  (wildlint {code} — {name})
#
# Provenance: {provenance}
#
# Invariant: a humanizer must never emit a mantissa >= base while a larger unit
# is still available. {func}(999999) must be "1M", never "1000k". This class of
# bug has no stable AST signature (it is reached by <=-vs-<, a missing carry, or
# rounding an unrounded boundary), so it is checked as a property, not a lint.

from wildlint.property_templates import find_rollover
from {import_from} import {func}


def test_no_rounding_rollover():
    # base={base}: use 1000 for SI/metric humanizers, 1024 for binary bytes.
    violations = find_rollover({func}, base={base})
    assert not violations, "\\n".join(str(v) for v in violations)


# --- Self-contained hypothesis variant (no wildlint dependency) --------------
# Uncomment if you prefer hypothesis. Fill in TOP_UNITS with your largest
# suffix(es) so legitimate past-the-table outputs are not flagged.
#
# import re
# from hypothesis import given, strategies as st
#
# TOP_UNITS = {{"P", "Pi"}}  # <- your largest unit suffix(es)
#
# @given(st.integers(min_value=1, max_value=10**18))
# def test_no_rollover_hypothesis(n):
#     out = {func}(n)
#     m = re.match(r"\\s*([+-]?\\d+(?:\\.\\d+)?)\\s*(.*?)\\s*$", out)
#     mantissa, unit = float(m.group(1)), m.group(2).strip()
#     assert abs(mantissa) < {base} or unit in TOP_UNITS, (
#         f"{func}({{n}}) -> {{out!r}}: mantissa >= {base} with a smaller unit"
#     )
"""


@dataclass(frozen=True)
class PropertyTemplate:
    """A property-test recipe for a class that resists a static rule."""

    code: str
    name: str
    tier: str
    description: str
    provenance: tuple[str, ...]
    check: Callable[..., list[Violation]]
    _render: Callable[..., str] = field(repr=False)

    def render(self, **kwargs: object) -> str:
        """Emit a ready-to-paste pytest module for this property."""
        return self._render(self, **kwargs)


def _render_rollover(
    tmpl: PropertyTemplate,
    *,
    func: str = "humanize",
    import_from: str = "yourmodule",
    base: int = 1000,
) -> str:
    return _RENDERED.format(
        code=tmpl.code,
        name=tmpl.name,
        provenance=", ".join(tmpl.provenance),
        func=func,
        import_from=import_from,
        base=base,
    )


ROLLOVER = PropertyTemplate(
    code="WP001",
    name="rounding-rollover",
    tier=DEFAULT,
    description=(
        "A number/byte/SI humanizer emits a mantissa >= base while a larger "
        "unit is still available (e.g. '1000k' instead of '1M'), because the "
        "unit is chosen before the mantissa is rounded."
    ),
    provenance=(
        "boltons#403",
        "millify#13",
        "numerize#17",
        "si-prefix#17",
    ),
    check=find_rollover,
    _render=_render_rollover,
)

TEMPLATES = [ROLLOVER]


def get_template(code_or_name: str) -> PropertyTemplate | None:
    """Look a template up by ``code`` (``WP001``) or ``name`` (``rollover``)."""
    key = code_or_name.strip().lower()
    for t in TEMPLATES:
        if key in (t.code.lower(), t.name.lower(), t.name.replace("rounding-", "")):
            return t
    return None
