"""Unit tests for app.analysis.confidence.calculator."""

from __future__ import annotations

import os

os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("STATE_SECRET", "test-secret")


class TestConfidenceCalculator:
    def setup_method(self):
        from app.analysis.confidence.calculator import (
            CalibrationData,
            ConfidenceCalculator,
            ConfidenceInputs,
        )

        self.Calculator = ConfidenceCalculator
        self.CalibrationData = CalibrationData
        self.Inputs = ConfidenceInputs
        self.calc = ConfidenceCalculator()

    def _make_inputs(self, **kwargs):
        defaults = dict(
            prediction_type="risk_tier",
            ai_self_report=70,
            ai_tier="medium",
            deterministic_tier="medium",
            required_retry=False,
            evidence_complete=True,
            calibration=None,
        )
        defaults.update(kwargs)
        return self.Inputs(**defaults)

    def test_output_bounded_0_to_100(self):
        for _ in range(10):
            inputs = self._make_inputs(
                ai_self_report=100, evidence_complete=True, required_retry=False
            )
            result = self.calc.compute_confidence(inputs)
            assert 0.0 <= result <= 100.0

    def test_cold_start_cap_applies_without_calibration(self):
        inputs = self._make_inputs(
            ai_self_report=100, evidence_complete=True, required_retry=False, calibration=None
        )
        result = self.calc.compute_confidence(inputs)
        assert result <= 85.0, f"Cold-start cap exceeded: {result}"

    def test_agreement_raises_confidence(self):
        agree = self._make_inputs(ai_tier="medium", deterministic_tier="medium")
        disagree = self._make_inputs(ai_tier="critical", deterministic_tier="low")
        assert self.calc.compute_confidence(agree) > self.calc.compute_confidence(disagree)

    def test_retry_lowers_confidence(self):
        no_retry = self._make_inputs(required_retry=False)
        with_retry = self._make_inputs(required_retry=True)
        assert self.calc.compute_confidence(no_retry) > self.calc.compute_confidence(with_retry)

    def test_evidence_complete_raises_confidence(self):
        complete = self._make_inputs(evidence_complete=True)
        incomplete = self._make_inputs(evidence_complete=False)
        assert self.calc.compute_confidence(complete) > self.calc.compute_confidence(incomplete)

    def test_positive_calibration_boosts_confidence(self):
        cal = self.CalibrationData(
            prediction_type="risk_tier",
            helpful_count=80,
            unhelpful_count=20,
        )
        with_cal = self._make_inputs(calibration=cal)
        no_cal = self._make_inputs(calibration=None)
        result_with = self.calc.compute_confidence(with_cal)
        result_without = self.calc.compute_confidence(no_cal)
        assert result_with >= result_without

    def test_negative_calibration_lowers_confidence(self):
        bad_cal = self.CalibrationData(
            prediction_type="risk_tier",
            helpful_count=10,
            unhelpful_count=90,
        )
        inputs = self._make_inputs(calibration=bad_cal)
        result = self.calc.compute_confidence(inputs)
        assert result <= 85.0

    def test_thin_calibration_ignored(self):
        """Below min_samples threshold, calibration should not be applied."""
        thin_cal = self.CalibrationData(
            prediction_type="risk_tier", helpful_count=5, unhelpful_count=1
        )
        inputs = self._make_inputs(calibration=thin_cal)
        result = self.calc.compute_confidence(inputs)
        assert result <= 85.0  # Cold-start cap still applies

    def test_confidence_band_high(self):
        assert self.calc.get_confidence_band(85.0) == "high"
        assert self.calc.get_confidence_band(80.0) == "high"

    def test_confidence_band_moderate(self):
        assert self.calc.get_confidence_band(65.0) == "moderate"
        assert self.calc.get_confidence_band(50.0) == "moderate"

    def test_confidence_band_low(self):
        assert self.calc.get_confidence_band(49.9) == "low"
        assert self.calc.get_confidence_band(0.0) == "low"

    def test_missing_ai_tier_uses_neutral(self):
        inputs = self._make_inputs(ai_tier=None, deterministic_tier=None)
        result = self.calc.compute_confidence(inputs)
        assert 0.0 <= result <= 100.0
