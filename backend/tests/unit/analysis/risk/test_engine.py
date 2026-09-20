"""Unit tests for app.analysis.risk.engine — Hybrid Risk Engine."""

from __future__ import annotations

import os

os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("STATE_SECRET", "test-secret")


class TestDeterministicSignalExtraction:
    def setup_method(self):
        from app.analysis.risk.engine import RiskEngine

        self.engine = RiskEngine()

    def test_sensitive_path_detected(self):
        signals = self.engine.compute_deterministic_signals(
            ["auth/login.py", "utils/helpers.py"], 50, 10
        )
        assert "auth/login.py" in signals.sensitive_paths_touched

    def test_no_sensitive_path(self):
        signals = self.engine.compute_deterministic_signals(
            ["src/utils.py", "tests/test_utils.py"], 20, 5
        )
        assert signals.sensitive_paths_touched == []

    def test_test_changes_detected(self):
        signals = self.engine.compute_deterministic_signals(
            ["tests/test_foo.py", "src/foo.py"], 30, 10
        )
        assert signals.has_test_changes is True
        assert signals.has_source_changes is True

    def test_no_test_with_source(self):
        signals = self.engine.compute_deterministic_signals(["src/foo.py", "src/bar.py"], 30, 10)
        assert signals.has_test_changes is False
        assert signals.has_source_changes is True

    def test_db_migration_detected(self):
        signals = self.engine.compute_deterministic_signals(["migrations/0001_add_table.py"], 20, 0)
        assert signals.has_db_migration is True

    def test_dependency_manifest_detected(self):
        signals = self.engine.compute_deterministic_signals(
            ["requirements.txt", "src/app.py"], 5, 2
        )
        assert signals.has_dependency_manifest is True

    def test_lines_changed_counted(self):
        signals = self.engine.compute_deterministic_signals([], 200, 100)
        assert signals.lines_changed == 300

    def test_config_infra_detected(self):
        signals = self.engine.compute_deterministic_signals([".github/workflows/ci.yml"], 10, 2)
        assert signals.has_config_or_infra is True


class TestRiskTierCombination:
    def setup_method(self):
        from app.analysis.risk.engine import DeterministicSignals, RiskEngine

        self.engine = RiskEngine()
        self.Signals = DeterministicSignals

    def test_low_risk_no_signals(self):
        signals = self.Signals()
        result = self.engine.assess_risk(signals, ai_risk_signal=None)
        assert result.risk_tier == "low"
        assert result.source == "deterministic_only"

    def test_sensitive_path_raises_to_medium_or_higher(self):
        signals = self.Signals(sensitive_paths_touched=["auth/login.py"])
        result = self.engine.assess_risk(signals, ai_risk_signal=None)
        assert result.risk_tier in ("medium", "high", "critical")

    def test_ai_cannot_lower_deterministic_tier(self):
        """AI proposes 'low' but deterministic says 'high' → keep 'high'."""
        signals = self.Signals(
            sensitive_paths_touched=["payments/charge.py"],
            has_db_migration=True,
            lines_changed=600,
        )
        result = self.engine.assess_risk(signals, ai_risk_signal="low")
        assert result.risk_tier != "low"
        assert result.source == "hybrid"
        # Rationale should explain the disagreement
        factor_names = [f["factor"] for f in result.rationale["factors"]]
        assert any(
            "override" in name.lower() or "disagree" in name.lower() for name in factor_names
        )

    def test_ai_can_escalate_tier(self):
        """AI proposes 'critical' but deterministic says 'low' → escalate."""
        signals = self.Signals()  # No deterministic signals → low
        result = self.engine.assess_risk(signals, ai_risk_signal="critical")
        assert result.risk_tier == "critical"
        assert result.source == "hybrid"

    def test_agreement_recorded_in_rationale(self):
        """When AI agrees with deterministic, rationale reflects agreement."""
        signals = self.Signals()
        result = self.engine.assess_risk(signals, ai_risk_signal="low")
        factor_names = [f["factor"] for f in result.rationale["factors"]]
        assert any("agreement" in n.lower() for n in factor_names)

    def test_no_ai_signal_is_deterministic_only(self):
        signals = self.Signals(sensitive_paths_touched=["auth/login.py"])
        result = self.engine.assess_risk(signals, ai_risk_signal=None)
        assert result.source == "deterministic_only"

    def test_invalid_ai_signal_ignored(self):
        signals = self.Signals()
        result = self.engine.assess_risk(signals, ai_risk_signal="INVALID_TIER")
        assert result.source == "deterministic_only"

    def test_large_diff_contributes_to_risk(self):
        signals = self.Signals(lines_changed=1500)
        result = self.engine.assess_risk(signals, ai_risk_signal=None)
        assert result.risk_tier in ("high", "critical")

    def test_rationale_always_present(self):
        """Every result must have a rationale, even for 'low' with no signals."""
        from app.analysis.risk.engine import DeterministicSignals

        signals = DeterministicSignals()
        result = self.engine.assess_risk(signals, None)
        assert "factors" in result.rationale
        assert isinstance(result.rationale["factors"], list)

    def test_risk_result_fields_all_present(self):
        from app.analysis.risk.engine import DeterministicSignals

        signals = DeterministicSignals()
        result = self.engine.assess_risk(signals, "medium")
        assert result.risk_tier in ("low", "medium", "high", "critical")
        assert isinstance(result.deterministic_score, float)
        assert isinstance(result.rationale, dict)
        assert result.source in ("deterministic_only", "hybrid")
