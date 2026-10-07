"""Registry of rulesets keyed by ``(series, year)``.

Adding a series or a year is a one-line change here plus a module; nothing
else in the workbench needs to know which rulebooks exist.
"""

from __future__ import annotations

from typing import Callable

from .base import RuleSet
from .fsae_us.y2026 import FsaeUs2026
from .fsae_us.y2027 import FsaeUs2027

RULESETS: dict[tuple[str, int], Callable[[], RuleSet]] = {
    ("fsae_us", 2026): FsaeUs2026,
    ("fsae_us", 2027): FsaeUs2027,
}


class UnknownRuleSet(KeyError):
    """No ruleset is registered for the requested series and year."""


def get(series: str, year: int) -> RuleSet:
    """Return the ruleset for ``(series, year)``."""
    try:
        factory = RULESETS[(series, year)]
    except KeyError:
        raise UnknownRuleSet(
            f"no ruleset for ({series!r}, {year}); available: {available()}"
        ) from None
    return factory()


def available() -> list[tuple[str, int]]:
    """Every registered ``(series, year)`` pair, sorted."""
    return sorted(RULESETS)
