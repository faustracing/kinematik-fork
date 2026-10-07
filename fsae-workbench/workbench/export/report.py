"""A report of a solved design: static metrics and sweep figures.

The numbers are the solver's. Anti-dive is the front axle's ``anti_dive``
metric and anti-squat is the rear axle's ``anti_squat`` metric — the flat keys
``anti_dive_left`` / ``anti_dive_right`` and ``anti_squat_left`` /
``anti_squat_right``. Nothing here recomputes them or files them under another
name.

:func:`build_report` is pure data. :func:`render_pdf` draws it, and needs
matplotlib (the ``report`` extra).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from workbench.core.design import Design
from workbench.solve.bridge import SolveFinding, SolveResult

__all__ = [
    "AxleReport",
    "DesignReport",
    "StaticMetric",
    "SweepFigure",
    "SweepSeries",
    "build_report",
    "render_pdf",
]

_SIDES: tuple[str, ...] = ("left", "right")
_TRAVEL = "wheel_travel"
_AXLE_ORDER = {"front": 0, "rear": 1}
_MIN_CURVE_POINTS = 2


@dataclass(frozen=True, slots=True)
class _Spec:
    """One solver metric the report knows how to present."""

    stem: str
    label: str
    unit: str
    scope: Literal["corner", "axle"]


# Stems are the solver's column names. Corner metrics gain a ``_left`` or
# ``_right`` suffix at the flat export boundary; axle metrics do not.
_CORNER: tuple[_Spec, ...] = (
    _Spec("camber", "Camber", "deg", "corner"),
    _Spec("toe_angle", "Toe", "deg", "corner"),
    _Spec("caster", "Caster", "deg", "corner"),
    _Spec("kpi", "KPI", "deg", "corner"),
    _Spec("scrub_radius", "Scrub radius", "mm", "corner"),
    _Spec("mechanical_trail", "Mechanical trail", "mm", "corner"),
    _Spec("deriv_camber_wrt_hub_z", "Camber gain", "deg/mm", "corner"),
    _Spec("deriv_toe_angle_wrt_hub_z", "Bump steer", "deg/mm", "corner"),
    _Spec(
        "deriv_spring_length_wrt_hub_z",
        "Spring per wheel travel",
        "mm/mm",
        "corner",
    ),
)
_AXLE: tuple[_Spec, ...] = (
    _Spec("roll_center_z", "Roll centre height", "mm", "axle"),
    _Spec("track", "Track", "mm", "axle"),
)
_ANTI: dict[str, _Spec] = {
    "front": _Spec("anti_dive", "Anti-dive", "%", "corner"),
    "rear": _Spec("anti_squat", "Anti-squat", "%", "corner"),
}
_CURVES: tuple[_Spec, ...] = (
    _Spec("camber", "Camber", "deg", "corner"),
    _Spec("toe_angle", "Toe", "deg", "corner"),
    _Spec("roll_center_z", "Roll centre height", "mm", "axle"),
)


@dataclass(frozen=True, slots=True)
class StaticMetric:
    """One number at the static step, addressed by the solver's own key.

    Attributes:
        key: Flat solver key. Corner metrics keep their ``_left`` / ``_right``
            suffix. Anti-geometry is ``anti_dive_*`` on the front and
            ``anti_squat_*`` on the rear.
        label: Display name. The key is not rewritten to match it.
        value: The value at the static step.
        unit: Unit symbol (``deg``, ``mm``, ``%``, ``deg/mm``, ``mm/mm``).
        side: ``"left"``, ``"right"``, or ``None`` for an axle metric.
    """

    key: str
    label: str
    value: float
    unit: str
    side: str | None = None


@dataclass(frozen=True, slots=True)
class SweepSeries:
    """One curve of a solver metric against wheel travel.

    Attributes:
        key: Flat solver key of the dependent metric.
        x_key: Flat solver key of the travel axis, ``wheel_travel`` plus a side.
        x: Travel samples, millimetres. Finite pairs only.
        y: Metric samples paired with ``x``.
    """

    key: str
    x_key: str
    x: tuple[float, ...]
    y: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class SweepFigure:
    """One sweep chart.

    Attributes:
        title: Figure title, including the axle and the sweep name.
        y_key: Solver metric stem (``camber``, ``anti_dive``, ``anti_squat``,
            ``roll_center_z``). Not a display alias.
        x_label: Axis label. The quantity is the solver's ``wheel_travel``.
        y_label: Axis label, display name plus unit.
        series: One entry per side, or one entry for an axle metric.
    """

    title: str
    y_key: str
    x_label: str
    y_label: str
    series: tuple[SweepSeries, ...]


@dataclass(frozen=True, slots=True)
class AxleReport:
    """The solved metrics of one axle.

    Attributes:
        axle: ``"front"`` or ``"rear"``.
        sweep: Sweep template name, or ``"custom"``.
        converged: True only when every step converged.
        fingerprint: Fingerprint the result was solved from.
        metrics: Static values whose solver keys were present and finite.
        figures: Sweep curves with at least two finite samples.
        findings: Solver findings, plus a note when the fingerprint does not
            match the design being reported.
    """

    axle: str
    sweep: str
    converged: bool
    fingerprint: str
    metrics: tuple[StaticMetric, ...]
    figures: tuple[SweepFigure, ...]
    findings: tuple[SolveFinding, ...]


@dataclass(frozen=True, slots=True)
class DesignReport:
    """A solved design, one section per axle that was passed in.

    Attributes:
        name: Design name.
        fingerprint: :meth:`Design.fingerprint` of the design being reported.
        axles: Front before rear when both are present.
    """

    name: str
    fingerprint: str
    axles: tuple[AxleReport, ...]

    def axle(self, name: str) -> AxleReport:
        """Return one axle section.

        Raises:
            KeyError: When the report has no section for that axle.
        """
        for item in self.axles:
            if item.axle == name:
                return item
        raise KeyError(
            f"Report {self.name!r} has no {name!r} axle; "
            f"present: {sorted(item.axle for item in self.axles)}"
        )


def build_report(design: Design, results: Mapping[str, SolveResult]) -> DesignReport:
    """Collect static metrics and sweep figures from solved axles.

    Args:
        design: The design the report is about. Its fingerprint is stamped on
            the report, and compared with each result's fingerprint.
        results: One :class:`SolveResult` per axle, keyed by that axle's id.
            The key has to match ``SolveResult.axle``.

    Returns:
        The report. A metric the solver did not emit is absent, not zero.

    Raises:
        ValueError: When a result is filed under a different axle than its own.
    """
    sections: list[AxleReport] = []
    for key, result in results.items():
        if result.axle != key:
            raise ValueError(
                f"Result for axle {result.axle!r} was passed under {key!r}"
            )
        sections.append(_axle_report(design, result))
    sections.sort(key=lambda item: _AXLE_ORDER.get(item.axle, 99))
    return DesignReport(
        name=design.name,
        fingerprint=design.fingerprint(),
        axles=tuple(sections),
    )


def render_pdf(report: DesignReport, path: str | Path) -> Path:
    """Draw the report to a PDF.

    The first pages are the static metrics. Each sweep figure follows on its
    own page. A marker sits on the sample nearest zero wheel travel, which is
    the static condition for a sweep that straddles it.

    Args:
        report: The report to draw.
        path: Destination. Parent directories are created.

    Returns:
        The path written.

    Raises:
        ImportError: When matplotlib is not installed.
    """
    destination = Path(path)
    plt = _pyplot()
    from matplotlib.backends.backend_pdf import PdfPages

    destination.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(destination) as pdf:
        for figure in _metric_pages(plt, report):
            pdf.savefig(figure)
            plt.close(figure)
        for axle in report.axles:
            for sweep in axle.figures:
                figure = _sweep_page(plt, report, axle, sweep)
                pdf.savefig(figure)
                plt.close(figure)
    return destination


def _axle_report(design: Design, result: SolveResult) -> AxleReport:
    """One axle section, including a finding when the solve is stale."""
    findings = result.findings
    if result.fingerprint and result.fingerprint != design.fingerprint():
        findings = (
            *findings,
            SolveFinding(
                severity="INFO",
                message=(
                    "Solved fingerprint does not match this design; "
                    "the figures describe a different geometry"
                ),
            ),
        )
    return AxleReport(
        axle=result.axle,
        sweep=result.sweep,
        converged=result.converged,
        fingerprint=result.fingerprint,
        metrics=_static_metrics(result),
        figures=_figures(result),
        findings=findings,
    )


def _specs_for(axle: str, curves: bool) -> tuple[_Spec, ...]:
    """Metric specs for one axle.

    Anti-dive is requested only on the front, anti-squat only on the rear.
    The other axle's anti metric is not read, even when the solver emitted it.
    """
    base = _CURVES if curves else (*_CORNER, *_AXLE)
    anti = _ANTI.get(axle)
    if anti is None:
        return base
    return (*base, anti)


def _static_metrics(result: SolveResult) -> tuple[StaticMetric, ...]:
    """Finite static values, in spec order, both sides where the solver has them."""
    found: list[StaticMetric] = []
    for spec in _specs_for(result.axle, curves=False):
        if spec.scope == "axle":
            value = _finite_static(result, spec.stem)
            if value is None:
                continue
            found.append(StaticMetric(spec.stem, spec.label, value, spec.unit))
            continue
        for side in _SIDES:
            key = f"{spec.stem}_{side}"
            value = _finite_static(result, key)
            if value is None:
                continue
            found.append(StaticMetric(key, spec.label, value, spec.unit, side))
    return tuple(found)


def _figures(result: SolveResult) -> tuple[SweepFigure, ...]:
    """Sweep curves against ``wheel_travel``. A single sample is not a curve."""
    figures: list[SweepFigure] = []
    for spec in _specs_for(result.axle, curves=True):
        series: list[SweepSeries] = []
        if spec.scope == "axle":
            x_key = f"{_TRAVEL}_left"
            points = _curve(result, x_key, spec.stem)
            if points is not None:
                series.append(_series(spec.stem, x_key, points))
        else:
            for side in _SIDES:
                key = f"{spec.stem}_{side}"
                x_key = f"{_TRAVEL}_{side}"
                points = _curve(result, x_key, key)
                if points is None:
                    continue
                series.append(_series(key, x_key, points))
        if not series:
            continue
        figures.append(
            SweepFigure(
                title=(f"{result.axle} {spec.label} vs wheel travel ({result.sweep})"),
                y_key=spec.stem,
                x_label="wheel_travel (mm)",
                y_label=f"{spec.label} ({spec.unit})",
                series=tuple(series),
            )
        )
    return tuple(figures)


def _series(
    key: str, x_key: str, points: tuple[tuple[float, float], ...]
) -> SweepSeries:
    """Pack paired samples into a series."""
    return SweepSeries(
        key=key,
        x_key=x_key,
        x=tuple(point[0] for point in points),
        y=tuple(point[1] for point in points),
    )


def _finite_static(result: SolveResult, key: str) -> float | None:
    """The static value of one metric, or ``None`` when it is absent or not finite."""
    try:
        value = result.static()[key]
    except KeyError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _curve(
    result: SolveResult, x_key: str, y_key: str
) -> tuple[tuple[float, float], ...] | None:
    """Finite ``(travel, metric)`` pairs, or ``None`` when fewer than two exist."""
    if x_key not in result.metrics or y_key not in result.metrics:
        return None
    xs = result.metrics[x_key]
    ys = result.metrics[y_key]
    points = tuple(
        (xs[index], ys[index])
        for index in range(min(len(xs), len(ys)))
        if math.isfinite(xs[index]) and math.isfinite(ys[index])
    )
    if len(points) < _MIN_CURVE_POINTS:
        return None
    return points


def _pyplot():
    """Import pyplot on the Agg backend.

    Raises:
        ImportError: When matplotlib is not installed, naming the extra.
    """
    try:
        import matplotlib
    except ImportError as error:
        raise ImportError(
            'PDF reports need matplotlib. Install it with pip install -e ".[report]"'
        ) from error
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    return plt


def _metric_lines(report: DesignReport) -> list[str]:
    """Monospace lines for the static-metric pages."""
    lines = [report.name, f"fingerprint {report.fingerprint}", ""]
    if not report.axles:
        lines.append("No solved axles were passed to the report.")
        return lines
    for axle in report.axles:
        state = "converged" if axle.converged else "DID NOT CONVERGE"
        lines.append(f"{axle.axle}  {axle.sweep}  {state}")
        if not axle.metrics:
            lines.append("  (no static metrics)")
        for metric in axle.metrics:
            side = metric.side or "axle"
            lines.append(
                f"  {metric.label:<28} {side:<5} {metric.value:12.6f} "
                f"{metric.unit:<8} {metric.key}"
            )
        for finding in axle.findings:
            where = "" if finding.step is None else f" step {finding.step}"
            lines.append(f"  {finding.severity}{where}: {finding.message}")
        lines.append("")
    return lines


def _metric_pages(plt, report: DesignReport) -> list:
    """One figure per page of static metrics."""
    lines = _metric_lines(report)
    page = 46
    chunks = [lines[index : index + page] for index in range(0, len(lines), page)]
    figures = []
    for index, chunk in enumerate(chunks, start=1):
        figure = plt.figure(figsize=(8.27, 11.69))
        figure.patch.set_facecolor("white")
        subtitle = "Static metrics"
        if len(chunks) > 1:
            subtitle += f" ({index}/{len(chunks)})"
        figure.text(0.07, 0.97, subtitle, fontsize=14, va="top")
        figure.text(
            0.07,
            0.945,
            "Anti-dive is the front axle metric anti_dive. "
            "Anti-squat is the rear axle metric anti_squat.",
            fontsize=8,
            color="#333333",
            va="top",
        )
        figure.text(
            0.07,
            0.92,
            "\n".join(chunk),
            fontsize=7.5,
            family="monospace",
            va="top",
        )
        figures.append(figure)
    return figures


def _sweep_page(plt, report: DesignReport, axle: AxleReport, sweep: SweepFigure):
    """One sweep figure. The marker is the sample nearest zero travel."""
    figure, axis = plt.subplots(figsize=(8.27, 5.5))
    for series in sweep.series:
        label = series.key.removeprefix(sweep.y_key).lstrip("_") or sweep.y_key
        static = min(range(len(series.x)), key=lambda index: abs(series.x[index]))
        axis.plot(
            series.x,
            series.y,
            label=label,
            linewidth=1.4,
            marker="o",
            markevery=[static],
        )
    axis.axvline(0.0, color="#bbbbbb", linewidth=0.7)
    axis.set_xlabel(sweep.x_label)
    axis.set_ylabel(sweep.y_label)
    axis.set_title(sweep.title)
    axis.grid(True, color="#e6e6e6")
    axis.legend(frameon=False)
    figure.text(
        0.01,
        0.01,
        f"{report.name}  {report.fingerprint[:12]}  {axle.sweep}",
        fontsize=7,
        color="#666666",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    return figure
