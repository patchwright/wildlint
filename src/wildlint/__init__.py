"""wildlint — static checks distilled from real upstream bugs.

Each rule was born from a concrete bug fixed in a public project, generalized to
the smallest form that catches the class without flooding you with false
positives. See ``checkers.py`` for the rule provenance.
"""

from __future__ import annotations

from .checkers import CHECKERS, Finding, check_source
from .cli import main

__version__ = "0.1.1"

__all__ = ["CHECKERS", "Finding", "check_source", "main", "__version__"]
