"""Тесты Research Stress Test и общих диагностических формул."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from winnow.analysis.diagnostics import (
    breusch_pagan,
    design_matrix,
    influence_measures,
    leverage_values,
    robust_covariance,
    white_test,
)
from winnow.analysis.stress import (
    DEFAULT_BOOTSTRAP,
    ChallengeConfig,
    StressConfig,
    run_stress_test,
    suggest_checks,
)
from winnow.core.dataset import Dataset
from winnow.stats.regression import fit_linear
from winnow.stats.result import Result


def _dataset(n: int = 70, seed: int = 2026) -> tuple[Dataset, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(0, 1, n)
    x2 = rng.normal(0, 1, n)
    noise = rng.normal(0, 1 + 0.5 * np.abs(x1), n)
    y = 2.0 + 2.2 * x1 - 0.7 * x2 + noise
    frame = pd.DataFrame({"y": y, "x1": x1, "x2": x2, "control": rng.normal(0, 1, n)})
    frame.loc[2, "y"] = 18.0
    return Dataset.from_dataframe(frame, "stress"), frame


def _fit(frame: pd.DataFrame):
    fit = fit_linear(frame, "y", ["x1", "x2"], confidence=0.95)
    x = design_matrix([frame["x1"].to_numpy(), frame["x2"].to_numpy()])
    return fit, x


def test_robust_hc1_is_hc0_times_df_factor():
    _dataset_obj, frame = _dataset()
    fit, x = _fit(frame)
    hc0 = robust_covariance(x, fit.residuals, "HC0")
    hc1 = robust_covariance(x, fit.residuals, "HC1")
    factor = fit.n / (fit.n - x.shape[1])
    assert np.allclose(hc1, hc0 * factor, rtol=1e-10, atol=1e-12)


def test_robust_hc3_differs_from_ols_and_is_positive():
    _dataset_obj, frame = _dataset()
    fit, x = _fit(frame)
    hc3 = robust_covariance(x, fit.residuals, "HC3")
    assert np.all(np.diag(hc3) >= 0)
    assert not np.allclose(np.sqrt(np.diag(hc3)), fit.std_errors)


def test_leverage_sums_to_parameters_and_cooks_has_one_high_point():
    _dataset_obj, frame = _dataset()
    fit, x = _fit(frame)
    leverage = leverage_values(x)
    assert np.isclose(float(leverage.sum()), x.shape[1], atol=1e-8)
    measures = influence_measures(x, fit.residuals, fit.ms_residual)
    assert measures.cooks_max > 0
    assert len(measures.cooks) == len(frame)
    assert 2 in measures.influential


def test_breusch_pagan_and_white_return_valid_p_values():
    _dataset_obj, frame = _dataset()
    fit, x = _fit(frame)
    for test in (breusch_pagan(fit.residuals, x), white_test(fit.residuals, x)):
        assert test.p_value is None or 0 <= test.p_value <= 1
        assert test.statistic is None or test.statistic >= 0


def test_stress_report_contains_scenarios_and_robust_errors():
    dataset, _frame = _dataset()
    report = run_stress_test(
        dataset,
        StressConfig(
            target="y",
            predictors=("x1", "x2"),
            bootstrap=40,
            seed=1,
        ),
    )
    assert report.baseline.id == "baseline"
    assert {scenario.id for scenario in report.scenarios} >= {
        "drop_x1",
        "drop_x2",
        "drop_outliers",
    }
    assert set(report.robust) == {"HC0", "HC1", "HC2", "HC3"}
    assert report.bootstrap is not None
    assert report.bootstrap.valid > 0
    assert report.as_payload()["baseline"]["n"] == 70
    assert any(item.kind == "caution" for item in report.findings)


def test_bootstrap_same_seed_is_reproducible_and_other_seed_differs():
    dataset, _frame = _dataset()
    config = StressConfig(
        target="y",
        predictors=("x1", "x2"),
        checks=("bootstrap",),
        bootstrap=30,
        seed=99,
    )
    first = run_stress_test(dataset, config)
    second = run_stress_test(dataset, config)
    assert first.bootstrap is not None and second.bootstrap is not None
    assert first.bootstrap.coefficients == second.bootstrap.coefficients

    other = run_stress_test(
        dataset,
        StressConfig(
            target="y",
            predictors=("x1", "x2"),
            checks=("bootstrap",),
            bootstrap=30,
            seed=100,
        ),
    )
    assert other.bootstrap is not None
    assert (
        other.bootstrap.coefficients["x1"]["mean"]
        != first.bootstrap.coefficients["x1"]["mean"]
    )


def test_stress_does_not_modify_source_frame():
    dataset, frame = _dataset()
    before = frame.copy(deep=True)
    run_stress_test(
        dataset,
        StressConfig(
            target="y",
            predictors=("x1", "x2"),
            bootstrap=20,
            seed=5,
        ),
    )
    pd.testing.assert_frame_equal(frame, before)


def test_custom_rows_are_excluded_and_report_roundtrips():
    dataset, _frame = _dataset()
    result = run_stress_test(
        dataset,
        StressConfig(
            target="y",
            predictors=("x1", "x2"),
            checks=("diagnostics",),
            bootstrap=0,
            exclude_rows=(2, 7),
        ),
    )
    scenario = next(item for item in result.scenarios if item.id == "exclude_rows")
    assert scenario.n == result.baseline.n - 2
    assert "Строки: 2, 7" in scenario.notes

    restored = Result.from_payload(result.as_result().as_payload())
    assert restored.procedure == "stress_test"
    assert [table.title for table in restored.tables] == [
        table.title for table in result.as_result().tables
    ]

    with pytest.raises(ValueError, match="вне диапазона"):
        run_stress_test(
            dataset,
            StressConfig(
                target="y",
                predictors=("x1", "x2"),
                checks=("diagnostics",),
                bootstrap=0,
                exclude_rows=(999,),
            ),
        )


def test_add_controls_uses_new_column_and_reports_missing():
    dataset, _frame = _dataset()
    report = run_stress_test(
        dataset,
        StressConfig(
            target="y",
            predictors=("x1", "x2"),
            checks=("specifications",),
            add_controls=("control",),
            bootstrap=0,
        ),
    )
    added = next(item for item in report.scenarios if item.id == "add_controls")
    names = {item["name"] for item in added.coefficients}
    assert "control" in names
    assert added.n == 70


def test_auto_checks_and_validation():
    dataset, _frame = _dataset()
    checks = suggest_checks(dataset, "y", ("x1", "x2"))
    assert "diagnostics" in checks
    assert "bootstrap" in checks
    assert DEFAULT_BOOTSTRAP == 500

    with pytest.raises(ValueError):
        run_stress_test(
            dataset,
            StressConfig(target="missing", predictors=("x1",)),
        )
    with pytest.raises(ValueError):
        run_stress_test(
            dataset,
            StressConfig(target="y", predictors=("missing",)),
        )


def test_challenge_supports_expected_direction_and_uses_controls():
    dataset, _frame = _dataset()
    report = run_stress_test(
        dataset,
        StressConfig(
            target="y",
            predictors=("x1", "x2"),
            checks=("diagnostics", "influence", "robust", "specifications", "bootstrap"),
            bootstrap=40,
            seed=4,
            challenge=ChallengeConfig(
                hypothesis="x1 положительно связан с y",
                focal="x1",
                direction="positive",
                controls=("control",),
            ),
        ),
    )
    assert report.challenge is not None
    assert report.challenge.status == "supported"
    assert report.challenge.focal == "x1"
    assert any(item.id == "challenge_controls" for item in report.scenarios)
    controls_check = next(
        item for item in report.challenge.checks if item["id"] == "controls"
    )
    assert controls_check["status"] != "not_tested"
    baseline = next(
        item for item in report.challenge.checks if item["id"] == "baseline"
    )
    assert baseline["b"] is not None
    assert report.bootstrap is not None
    assert "positive_share" in report.bootstrap.coefficients["x1"]


def test_challenge_with_opposite_direction_is_contradicted():
    dataset, _frame = _dataset()
    report = run_stress_test(
        dataset,
        StressConfig(
            target="y",
            predictors=("x1", "x2"),
            checks=("diagnostics", "robust"),
            bootstrap=0,
            challenge=ChallengeConfig(
                hypothesis="x1 отрицательно связан с y",
                focal="x1",
                direction="negative",
            ),
        ),
    )
    assert report.challenge is not None
    assert report.challenge.status == "contradicted"
    assert any(item["id"] == "baseline" and item["status"] == "contradicts" for item in report.challenge.checks)


def test_challenge_rejects_focal_outside_model_and_control_inside_model():
    dataset, _frame = _dataset()
    with pytest.raises(ValueError, match="Фокус"):
        run_stress_test(
            dataset,
            StressConfig(
                target="y",
                predictors=("x1", "x2"),
                checks=("diagnostics",),
                challenge=ChallengeConfig(
                    hypothesis="Гипотеза",
                    focal="control",
                    direction="positive",
                ),
            ),
        )
    with pytest.raises(ValueError, match="уже входит"):
        run_stress_test(
            dataset,
            StressConfig(
                target="y",
                predictors=("x1", "x2"),
                checks=("diagnostics",),
                challenge=ChallengeConfig(
                    hypothesis="Гипотеза",
                    focal="x1",
                    direction="positive",
                    controls=("x2",),
                ),
            ),
        )
