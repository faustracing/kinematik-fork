"""Rule and ruleset protocols shared by every series and year.

A rule is one clause of a published rulebook, encoded with its real citation.
Rules come in two flavours, and most useful ones are both:

* a ``check`` that measures the design and returns a :class:`Finding`, and
* a ``regions`` contribution that hands the optimizer ``allow=False`` volumes
  so illegal geometry is unreachable during the search rather than merely
  reported afterwards.

Nothing in this package invents a limit. If a number cannot be read off the
rulebook the rule is omitted and recorded in ``GAPS.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from ..regions import Region

if TYPE_CHECKING:  # pragma: no cover - the scaffold owns this module
    from ..core.design import Design


class Severity(StrEnum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    citation: str
    severity: Severity
    message: str
    measured: float | None = None
    limit: float | None = None
    nodes: list[str] = []


class MissingData(Exception):
    """The design does not carry the field a rule needs to evaluate itself.

    Raised by the accessors in :mod:`workbench.rules._design_access` and turned
    into an ``INFO`` finding by :meth:`Rule.check`, so an incomplete model
    degrades to "verify this by hand" instead of a false pass or a crash.
    """


@runtime_checkable
class GeometryRule(Protocol):
    id: str
    citation: str
    description: str
    severity: Severity

    def check(self, design: "Design") -> Finding | None: ...
    def regions(self, design: "Design") -> list[Region]: ...


class Rule(ABC):
    """Concrete base for the encoded rules.

    Subclasses set the four metadata attributes and implement ``_check``;
    ``regions`` defaults to empty for non-geometric clauses.
    """

    id: str
    citation: str
    description: str
    severity: Severity = Severity.BLOCKER

    #: Set on rules that cannot be decided from the model and always report.
    advisory: bool = False

    def check(self, design: "Design") -> Finding | None:
        try:
            return self._check(design)
        except MissingData as exc:
            return self.finding(
                f"not verifiable from the model: {exc}", severity=Severity.INFO
            )

    @abstractmethod
    def _check(self, design: "Design") -> Finding | None: ...

    def regions(self, design: "Design") -> list[Region]:
        try:
            return self._regions(design)
        except MissingData:
            return []

    def _regions(self, design: "Design") -> list[Region]:
        return []

    # -- helpers --------------------------------------------------------------

    def finding(
        self,
        message: str,
        *,
        severity: Severity | None = None,
        measured: float | None = None,
        limit: float | None = None,
        nodes: list[str] | None = None,
    ) -> Finding:
        return Finding(
            rule_id=self.id,
            citation=self.citation,
            severity=severity or self.severity,
            message=message,
            measured=measured,
            limit=limit,
            nodes=nodes or [],
        )

    @property
    def region_source(self) -> str:
        return f"rule:{self.citation}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {self.id} {self.citation}>"


class RuleSetProtocol(Protocol):
    series: str
    year: int
    extends: "RuleSetProtocol | None"

    def rules(self) -> list[GeometryRule]: ...
    def check_all(self, design: "Design") -> list[Finding]: ...
    def illegal_regions(self, design: "Design") -> list[Region]: ...


class RuleSet:
    """A named, dated set of rules, optionally layered on an earlier year.

    ``own_rules`` are merged over the inherited ones by rule id, so a year that
    changes one clause ships only that clause. ``removed`` drops an inherited
    rule that a later rulebook deleted outright.
    """

    series: str
    year: int
    title: str = ""
    #: Human-readable provenance of the document the rules were read from.
    document: str = ""
    extends: "RuleSet | None" = None
    removed: frozenset[str] = frozenset()

    #: Set when the year's deltas have not been confirmed against a published
    #: rulebook. Surfaced as an INFO finding by ``check_all``.
    unverified: bool = False
    unverified_note: str = ""

    def own_rules(self) -> list[Rule]:
        return []

    def rules(self) -> list[GeometryRule]:
        merged: dict[str, Rule] = {}
        if self.extends is not None:
            for rule in self.extends.rules():
                merged[rule.id] = rule  # type: ignore[assignment]
        for rule_id in self.removed:
            merged.pop(rule_id, None)
        for rule in self.own_rules():
            merged[rule.id] = rule
        return sorted(merged.values(), key=lambda r: (r.citation, r.id))  # type: ignore[arg-type]

    def check_all(self, design: "Design") -> list[Finding]:
        findings: list[Finding] = []
        if self.unverified:
            findings.append(
                Finding(
                    rule_id=f"{self.series}.{self.year}.unverified",
                    citation="-",
                    severity=Severity.INFO,
                    message=self.unverified_note
                    or (
                        f"{self.series} {self.year} rules were not confirmed "
                        "against a published rulebook"
                    ),
                )
            )
        for rule in self.rules():
            found = rule.check(design)
            if found is not None:
                findings.append(found)
        return findings

    def illegal_regions(self, design: "Design") -> list[Region]:
        out: list[Region] = []
        for rule in self.rules():
            out.extend(rule.regions(design))
        return out

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RuleSet {self.series} {self.year}>"
