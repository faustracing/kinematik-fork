"""Reports of a solved design.

Anti-dive and anti-squat are read from the solver's own keys: ``anti_dive`` on
the front axle result and ``anti_squat`` on the rear. A value sitting on the
other axle under the other name is not reported.
"""

from __future__ import annotations

import math

import pytest
from workbench.export.report import build_report, render_pdf
from workbench.solve.bridge import SolveFinding, SolveResult

#: Pinned in ``test_golden_car`` from the golden CSV through the solver.
_FRONT_ANTI_DIVE = 31.00546235327764
_REAR_ANTI_SQUAT = -27.64220927910989


def _solved(
    axle: str,
    metrics: dict[str, list[float]],
    *,
    sweep: str = "bump",
    converged: bool = True,
    findings: tuple[SolveFinding, ...] = (),
    fingerprint: str = "",
) -> SolveResult:
    return SolveResult(
        axle=axle,
        sweep=sweep,
        converged=converged,
        findings=findings,
        metrics=metrics,
        fingerprint=fingerprint,
    )


def _travel() -> dict[str, list[float]]:
    return {
        "wheel_travel_left": [-25.0, 0.0, 25.0],
        "wheel_travel_right": [-25.0, 0.0, 25.0],
    }


class TestAntiGeometryKeys:
    def test_front_reads_anti_dive_and_ignores_anti_squat(self, golden_design):
        front = _solved(
            "front",
            {
                **_travel(),
                "anti_dive_left": [20.0, 31.0, 40.0],
                "anti_dive_right": [21.0, 31.5, 41.0],
                "anti_squat_left": [0.0, 999.0, 999.0],
                "camber_left": [1.0, 0.0, -1.0],
                "camber_right": [1.0, 0.0, -1.0],
            },
        )
        rear = _solved(
            "rear",
            {
                **_travel(),
                "anti_squat_left": [-20.0, -27.6, -30.0],
                "anti_squat_right": [-21.0, -27.7, -31.0],
                "anti_dive_left": [0.0, 999.0, 999.0],
            },
        )
        report = build_report(golden_design, {"rear": rear, "front": front})
        assert [item.axle for item in report.axles] == ["front", "rear"]

        front_keys = {metric.key for metric in report.axle("front").metrics}
        rear_keys = {metric.key for metric in report.axle("rear").metrics}
        assert "anti_dive_left" in front_keys
        assert "anti_dive_right" in front_keys
        assert "anti_squat_left" not in front_keys
        assert "anti_squat_left" in rear_keys
        assert "anti_squat_right" in rear_keys
        assert "anti_dive_left" not in rear_keys

        dive = next(
            metric
            for metric in report.axle("front").metrics
            if metric.key == "anti_dive_left"
        )
        assert dive.value == pytest.approx(31.0)
        assert dive.unit == "%"
        assert dive.side == "left"
        assert dive.label == "Anti-dive"

        curves = {figure.y_key for figure in report.axle("front").figures}
        assert "anti_dive" in curves
        assert "anti_squat" not in curves
        assert "camber" in curves
        rear_curves = {figure.y_key for figure in report.axle("rear").figures}
        assert rear_curves == {"anti_squat"}
        squat = next(
            figure
            for figure in report.axle("rear").figures
            if figure.y_key == "anti_squat"
        )
        assert squat.series[0].key == "anti_squat_left"
        assert squat.series[0].x_key == "wheel_travel_left"
        assert squat.series[0].y == pytest.approx((-20.0, -27.6, -30.0))

    def test_a_nan_anti_metric_is_omitted_rather_than_zeroed(self, golden_design):
        front = _solved(
            "front",
            {"anti_dive_left": [float("nan")], "camber_left": [float("nan")]},
        )
        report = build_report(golden_design, {"front": front})
        assert report.axle("front").metrics == ()
        assert report.axle("front").figures == ()

    def test_a_single_sample_is_a_static_number_and_not_a_curve(self, golden_design):
        front = _solved(
            "front",
            {
                "anti_dive_left": [12.0],
                "wheel_travel_left": [0.0],
                "camber_left": [0.5],
            },
        )
        axle = build_report(golden_design, {"front": front}).axle("front")
        assert axle.figures == ()
        assert any(
            metric.key == "anti_dive_left" and metric.value == pytest.approx(12.0)
            for metric in axle.metrics
        )


class TestReportShape:
    def test_a_failed_solve_keeps_the_finding_and_invents_nothing(self, golden_design):
        front = _solved(
            "front",
            {},
            converged=False,
            findings=(
                SolveFinding(
                    severity="BLOCKER", message="Solver did not converge: boom"
                ),
            ),
            fingerprint=golden_design.fingerprint(),
        )
        axle = build_report(golden_design, {"front": front}).axle("front")
        assert axle.converged is False
        assert axle.metrics == ()
        assert axle.figures == ()
        assert axle.findings[0].message == "Solver did not converge: boom"

    def test_a_stale_fingerprint_is_flagged(self, golden_design):
        front = _solved("front", {}, fingerprint="not-this-design")
        findings = build_report(golden_design, {"front": front}).axle("front").findings
        assert any(
            finding.severity == "INFO" and "fingerprint" in finding.message
            for finding in findings
        )

    def test_an_empty_fingerprint_is_not_called_stale(self, golden_design):
        front = _solved("front", {})
        assert (
            build_report(golden_design, {"front": front}).axle("front").findings == ()
        )

    def test_a_result_filed_under_the_wrong_axle_is_rejected(self, golden_design):
        rear = _solved("rear", {"anti_squat_left": [1.0]})
        with pytest.raises(ValueError, match="passed under 'front'"):
            build_report(golden_design, {"front": rear})

    def test_an_unsolved_report_has_no_axles(self, golden_design):
        report = build_report(golden_design, {})
        assert report.axles == ()
        assert report.fingerprint == golden_design.fingerprint()
        with pytest.raises(KeyError, match="no 'front' axle"):
            report.axle("front")


class TestPdf:
    def test_a_report_renders_to_a_pdf(self, golden_design, tmp_path):
        pytest.importorskip("matplotlib")
        front = _solved(
            "front",
            {
                **_travel(),
                "camber_left": [1.0, 0.0, -1.0],
                "camber_right": [1.1, 0.1, -0.9],
                "anti_dive_left": [20.0, 31.0, 40.0],
                "anti_dive_right": [20.0, 31.0, 40.0],
                "roll_center_z": [20.0, 25.0, 30.0],
            },
            fingerprint=golden_design.fingerprint(),
        )
        report = build_report(golden_design, {"front": front})
        path = render_pdf(report, tmp_path / "nested" / "report.pdf")
        data = path.read_bytes()
        assert data.startswith(b"%PDF")
        assert len(data) > 2000
        # Metrics page plus one page per curve: camber, roll centre, anti-dive.
        assert len(report.axle("front").figures) == 3


class TestGoldenCar:
    @pytest.mark.solver
    @pytest.mark.golden
    def test_the_golden_csv_reports_the_pinned_anti_geometry(
        self, golden_design, front_bump, rear_bump, tmp_path
    ):
        report = build_report(golden_design, {"front": front_bump, "rear": rear_bump})
        dive = next(
            metric
            for metric in report.axle("front").metrics
            if metric.key == "anti_dive_left"
        )
        squat = next(
            metric
            for metric in report.axle("rear").metrics
            if metric.key == "anti_squat_left"
        )
        assert dive.value == pytest.approx(front_bump.static()["anti_dive_left"])
        assert squat.value == pytest.approx(rear_bump.static()["anti_squat_left"])
        assert dive.value == pytest.approx(_FRONT_ANTI_DIVE)
        assert squat.value == pytest.approx(_REAR_ANTI_SQUAT)
        assert all(
            not metric.key.startswith("anti_squat")
            for metric in report.axle("front").metrics
        )
        assert all(
            not metric.key.startswith("anti_dive")
            for metric in report.axle("rear").metrics
        )

        dive_curve = next(
            figure
            for figure in report.axle("front").figures
            if figure.y_key == "anti_dive"
        )
        left = next(
            series for series in dive_curve.series if series.key == "anti_dive_left"
        )
        assert len(left.x) == front_bump.n_steps
        assert left.y[front_bump.n_steps // 2] == pytest.approx(_FRONT_ANTI_DIVE)
        assert not any(math.isnan(value) for value in left.y)

        pytest.importorskip("matplotlib")
        path = render_pdf(report, tmp_path / "golden.pdf")
        assert path.read_bytes().startswith(b"%PDF")
