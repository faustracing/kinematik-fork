"""Formula SAE US, 2027 season.

Source document: *Formula SAE Rules 2027*, Version 1.0, 1 September 2026
(fsaeonline.com, Series Resources). This is the official rulebook, not the
21 July 2026 public-comment draft, which GR.4.4 says is "not valid for
competition".

**Delta audit.** The V.1 Configuration, V.3 Suspension and Steering and V.4
Wheels and Tires sections of the 2027 document were compared line by line with
the same sections of the 2026 document. Every limit this package encodes is
unchanged:

===================================  ============  ============
Clause                               2026          2027
===================================  ============  ============
V.1.1.c keep-out margin              75 mm         75 mm
V.1.2 minimum wheelbase              1525 mm       1525 mm
V.1.3.2 minimum track ratio          75%           75%
V.1.4.2 Lower Side Impact Structure  90 mm max     90 mm max
V.3.1.1 usable wheel travel          50 mm         50 mm
V.3.2.5 steering free play           < 7 deg       < 7 deg
V.3.2.10.a rear steer range          6 deg max     6 deg max
V.4.1 minimum wheel diameter         203.2 mm      203.2 mm
V.4.3.2 wet tire tread depth         2.4 mm        2.4 mm
IN.11.2.2 tilt test angle            60 deg        60 deg
===================================  ============  ============

The only differences in those sections are editorial: V.2.1.1 says "thru"
rather than "up to", V.2.2.b drops the word "normal" before "driving
position", V.3.3.2/V.3.3.3/V.3.3.4 lose some trailing full stops, and
V.3.3.3 says "their driving position" rather than "the normal driving
position". None of them touch suspension or chassis geometry, so 2027 declares
no deltas and inherits the whole 2026 set.
"""

from __future__ import annotations

from ..base import Rule, RuleSet
from .y2026 import FsaeUs2026


class FsaeUs2027(RuleSet):
    series = "fsae_us"
    year = 2027
    title = "Formula SAE US 2027"
    document = "Formula SAE Rules 2027, Version 1.0, 1 September 2026"
    extends = FsaeUs2026()

    def own_rules(self) -> list[Rule]:
        # Verified against the published 2027 rulebook: no geometry-relevant
        # clause in V.1--V.4 or IN.11 changed from 2026. See the module
        # docstring for the clause-by-clause comparison.
        return []


RULESET = FsaeUs2027()
