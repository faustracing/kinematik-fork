from __future__ import annotations

import pytest

from workbench.rules import Severity
from workbench.rules.base import Rule, RuleSet
from workbench.rules.fsae_us.y2026 import FsaeUs2026
from workbench.rules.fsae_us.y2027 import FsaeUs2027
from workbench.rules.registry import UnknownRuleSet, available, get


def test_available_lists_the_shipped_rulebooks() -> None:
    assert available() == [("fsae_us", 2026), ("fsae_us", 2027)]


@pytest.mark.parametrize("key", available())
def test_get_returns_a_matching_ruleset(key: tuple[str, int]) -> None:
    series, year = key
    rs = get(series, year)
    assert (rs.series, rs.year) == key
    assert rs.rules()


def test_unknown_ruleset_names_the_alternatives() -> None:
    with pytest.raises(UnknownRuleSet, match=r"fsae_us"):
        get("fsg", 2026)


def test_every_rule_carries_real_metadata() -> None:
    for series, year in available():
        for rule in get(series, year).rules():
            assert rule.id and rule.id.islower()
            assert rule.citation and rule.citation[0] in "VFIT"
            assert rule.description
            assert isinstance(rule.severity, Severity)


def test_rule_ids_are_unique_within_a_ruleset() -> None:
    for series, year in available():
        ids = [r.id for r in get(series, year).rules()]
        assert len(ids) == len(set(ids))


def test_every_ruleset_names_its_source_document() -> None:
    assert "2026" in FsaeUs2026().document
    assert "Version 1.0" in FsaeUs2026().document
    assert "2027" in FsaeUs2027().document
    assert "Version 1.0" in FsaeUs2027().document


def test_shipped_rulesets_are_not_flagged_unverified() -> None:
    # Both documents were obtained and read, so nothing should be guessed at.
    for series, year in available():
        assert get(series, year).unverified is False


def test_2027_extends_2026_and_declares_no_geometry_deltas() -> None:
    y27 = FsaeUs2027()
    assert isinstance(y27.extends, FsaeUs2026)
    assert y27.own_rules() == []
    assert [r.id for r in y27.rules()] == [r.id for r in FsaeUs2026().rules()]


def test_extension_mechanism_overrides_by_id() -> None:
    class Tighter(Rule):
        id = "wheelbase_min"
        citation = "V.1.2"
        description = "test override"
        severity = Severity.WARNING

        def _check(self, design):  # type: ignore[no-untyped-def]
            return None

    class Y2028(RuleSet):
        series = "fsae_us"
        year = 2028
        extends = FsaeUs2026()
        unverified = True

        def own_rules(self) -> list[Rule]:
            return [Tighter()]

    rules = {r.id: r for r in Y2028().rules()}
    assert len(rules) == len(FsaeUs2026().rules())
    assert rules["wheelbase_min"].description == "test override"


def test_removed_drops_an_inherited_rule() -> None:
    class Y2028(RuleSet):
        series = "fsae_us"
        year = 2028
        extends = FsaeUs2026()
        removed = frozenset({"wheel_diameter_min"})

    ids = [r.id for r in Y2028().rules()]
    assert "wheel_diameter_min" not in ids
    assert "wheelbase_min" in ids
