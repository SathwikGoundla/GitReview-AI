"""Unit tests for app.analysis.checklist.generator."""

from __future__ import annotations

import os

os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("STATE_SECRET", "test-secret")

ALLOWED_CATEGORIES = {
    "security",
    "performance",
    "exception_handling",
    "null_handling",
    "logging",
    "testing",
    "documentation",
    "dependencies",
    "database_changes",
}


class TestDeterministicRules:
    def setup_method(self):
        from app.analysis.checklist.generator import ChecklistGenerator

        self.gen = ChecklistGenerator()

    def test_testing_triggered_when_source_no_tests(self):
        result = self.gen.generate_checklist(
            changed_files=["src/auth/login.py"],
            ai_checklist_signal=None,
        )
        cats = {item.category for item in result.items}
        assert "testing" in cats

    def test_testing_not_triggered_when_test_file_present(self):
        result = self.gen.generate_checklist(
            changed_files=["src/auth/login.py", "tests/test_login.py"],
            ai_checklist_signal=None,
        )
        # testing should NOT be triggered deterministically when tests are present
        deterministic_items = [i for i in result.items if i.trigger_source == "deterministic"]
        det_cats = {i.category for i in deterministic_items}
        assert "testing" not in det_cats

    def test_database_changes_triggered_by_migration(self):
        result = self.gen.generate_checklist(
            changed_files=["migrations/0001_add_users.py"],
            ai_checklist_signal=None,
        )
        cats = {item.category for item in result.items}
        assert "database_changes" in cats

    def test_dependencies_triggered_by_requirements(self):
        result = self.gen.generate_checklist(
            changed_files=["requirements.txt"],
            ai_checklist_signal=None,
        )
        cats = {item.category for item in result.items}
        assert "dependencies" in cats

    def test_security_triggered_by_auth_path(self):
        result = self.gen.generate_checklist(
            changed_files=["src/auth/oauth.py"],
            ai_checklist_signal=None,
        )
        cats = {item.category for item in result.items}
        assert "security" in cats

    def test_fallback_set_when_no_ai(self):
        result = self.gen.generate_checklist(
            changed_files=["src/auth/login.py"],
            ai_checklist_signal=None,
        )
        assert result.is_fallback is True

    def test_empty_files_produces_baseline_fallback(self):
        result = self.gen.generate_checklist(
            changed_files=[],
            ai_checklist_signal=None,
        )
        assert result.is_fallback is True
        cats = {item.category for item in result.items}
        assert "security" in cats
        assert "testing" in cats


class TestAISignalMerging:
    def setup_method(self):
        from app.analysis.checklist.generator import ChecklistGenerator

        self.gen = ChecklistGenerator()

    def _make_ai_signal(self, relevant_cats: list[str]) -> list[dict]:
        """Build a valid AI checklist signal with given categories marked relevant."""
        items = []
        for cat in ALLOWED_CATEGORIES:
            items.append(
                {
                    "category": cat,
                    "relevant": cat in relevant_cats,
                    "self_reported_confidence": 80 if cat in relevant_cats else 20,
                    "reason": "test",
                }
            )
        return items

    def test_ai_signal_adds_performance_item(self):
        signal = self._make_ai_signal(["performance"])
        result = self.gen.generate_checklist(
            changed_files=["src/utils.py"],
            ai_checklist_signal=signal,
        )
        cats = {item.category for item in result.items}
        assert "performance" in cats
        assert result.is_fallback is False

    def test_both_deterministic_and_ai_merged_as_both(self):
        """When testing is triggered deterministically AND by AI, trigger_source='both'."""
        signal = self._make_ai_signal(["testing"])
        result = self.gen.generate_checklist(
            changed_files=["src/foo.py"],  # No test file → deterministic testing trigger
            ai_checklist_signal=signal,
        )
        testing_items = [i for i in result.items if i.category == "testing"]
        assert len(testing_items) == 1
        assert testing_items[0].trigger_source == "both"

    def test_ai_only_item_has_trigger_source_ai(self):
        signal = self._make_ai_signal(["performance"])
        result = self.gen.generate_checklist(
            changed_files=["src/utils.py"],  # No deterministic performance trigger
            ai_checklist_signal=signal,
        )
        perf_items = [i for i in result.items if i.category == "performance"]
        assert len(perf_items) == 1
        assert perf_items[0].trigger_source == "ai"

    def test_invalid_category_in_ai_signal_skipped(self):
        """Categories not in allowed set must be silently skipped."""
        signal = self._make_ai_signal([])
        signal.append(
            {
                "category": "INVENTED_CATEGORY",
                "relevant": True,
                "self_reported_confidence": 90,
                "reason": "x",
            }
        )
        result = self.gen.generate_checklist(
            changed_files=["src/foo.py"],
            ai_checklist_signal=signal,
        )
        cats = {item.category for item in result.items}
        assert "INVENTED_CATEGORY" not in cats

    def test_malformed_ai_signal_falls_back(self):
        """Completely malformed AI signal should trigger fallback."""
        result = self.gen.generate_checklist(
            changed_files=["src/foo.py"],
            ai_checklist_signal="this is not a list",  # type: ignore
        )
        assert result.is_fallback is True

    def test_no_duplicate_categories(self):
        signal = self._make_ai_signal(["testing", "security"])
        result = self.gen.generate_checklist(
            changed_files=["src/auth/login.py"],  # triggers security deterministically
            ai_checklist_signal=signal,
        )
        cats = [item.category for item in result.items]
        assert len(cats) == len(set(cats)), "Duplicate categories found in checklist"

    def test_all_items_have_valid_categories(self):
        signal = self._make_ai_signal(["performance", "logging"])
        result = self.gen.generate_checklist(
            changed_files=["src/foo.py", "migrations/001.py"],
            ai_checklist_signal=signal,
        )
        for item in result.items:
            assert item.category in ALLOWED_CATEGORIES, f"Invalid category: {item.category}"

    def test_confidence_scores_bounded(self):
        signal = self._make_ai_signal(["performance"])
        result = self.gen.generate_checklist(
            changed_files=["src/foo.py"],
            ai_checklist_signal=signal,
        )
        for item in result.items:
            assert 0.0 <= item.confidence_score <= 100.0

    def test_ai_irrelevant_items_excluded(self):
        """Items the AI marks as not relevant should not appear (unless deterministic also fires)."""
        signal = self._make_ai_signal([])  # All irrelevant
        result = self.gen.generate_checklist(
            changed_files=["src/utils.py"],  # Only triggers testing deterministically
            ai_checklist_signal=signal,
        )
        cats = {item.category for item in result.items}
        # Should only have deterministically triggered items
        assert "performance" not in cats  # AI said not relevant, no deterministic trigger
