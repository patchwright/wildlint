"""wildlint — static checks distilled from real upstream bugs.

Each rule was born from a concrete bug fixed in a public project, generalized to
the smallest form that catches the class without flooding you with false
positives. See ``checkers.py`` for the rule provenance.
"""

from __future__ import annotations

from .checkers import CHECKERS, Finding, check_source
from .cli import main
from .property_templates import (
    TEMPLATES,
    Violation,
    find_date_kwargs,
    find_rollover,
    find_roundtrip,
    get_template,
)

__version__ = "0.7.0"

__all__ = [
    "CHECKERS",
    "Finding",
    "check_source",
    "main",
    "TEMPLATES",
    "Violation",
    "find_date_kwargs",
    "find_rollover",
    "find_roundtrip",
    "get_template",
    "__version__",
]
