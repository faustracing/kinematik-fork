"""Rulebook-derived checks and illegal regions, keyed by series and year.

    >>> from workbench.rules import registry
    >>> registry.available()
    [('fsae_us', 2026), ('fsae_us', 2027)]

Geometric clauses emit ``allow=False`` regions through
:meth:`RuleSet.illegal_regions`, so the optimizer can respect legality while it
searches instead of discovering violations afterwards. Non-geometric clauses
return :class:`Finding` objects only.
"""

from __future__ import annotations

from . import registry
from .base import (
    Finding,
    GeometryRule,
    MissingData,
    Rule,
    RuleSet,
    RuleSetProtocol,
    Severity,
)

__all__ = [
    "Finding",
    "GeometryRule",
    "MissingData",
    "Rule",
    "RuleSet",
    "RuleSetProtocol",
    "Severity",
    "registry",
]
