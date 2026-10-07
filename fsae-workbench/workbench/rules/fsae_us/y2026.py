"""Formula SAE US, 2026 season.

Source document: *Formula SAE Rules 2026*, Version 1.0, 10 Sept 2025
(fsaeonline.com, Series Resources). Clause text for V.1 Configuration,
V.3 Suspension and Steering, V.4 Wheels and Tires, and IN.11 Tilt Test was read
from that document; every limit in :mod:`._common` is transcribed from it.
"""

from __future__ import annotations

from ..base import Rule, RuleSet
from ._common import common_rules


class FsaeUs2026(RuleSet):
    series = "fsae_us"
    year = 2026
    title = "Formula SAE US 2026"
    document = "Formula SAE Rules 2026, Version 1.0, 10 Sept 2025"

    def own_rules(self) -> list[Rule]:
        return common_rules()


RULESET = FsaeUs2026()
