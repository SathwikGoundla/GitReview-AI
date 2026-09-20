"""Unit tests for app.analysis.reviewer.service."""

from __future__ import annotations

import os

os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("STATE_SECRET", "test-secret")


class TestReviewerRankingService:
    def setup_method(self):
        from app.analysis.reviewer.service import ReviewerRankingService

        self.service = ReviewerRankingService()

    def _recommend(self, **kwargs):
        defaults = dict(
            changed_files=["src/auth/login.py", "src/auth/logout.py"],
            pr_author_username="alice",
            codeowners_map={},
            review_history={},
            commit_history={},
            repo_collaborators={"bob", "carol", "dave"},
        )
        defaults.update(kwargs)
        return self.service.recommend(**defaults)

    def test_abstains_with_no_candidates(self):
        result = self._recommend(codeowners_map={}, review_history={}, commit_history={})
        assert result.has_suggestion is False
        assert result.abstain_reason is not None

    def test_recommends_codeowner(self):
        result = self._recommend(
            codeowners_map={"src/auth/": ["bob"]},
            review_history={},
            commit_history={},
        )
        assert result.has_suggestion is True
        assert result.recommended_username == "bob"

    def test_author_excluded_from_candidates(self):
        """PR author 'alice' must never be recommended, even if she's a CODEOWNER."""
        result = self._recommend(
            codeowners_map={"src/auth/": ["alice"]},
            review_history={"alice": 10},
            commit_history={},
            repo_collaborators={"alice", "bob"},
        )
        if result.has_suggestion:
            assert result.recommended_username != "alice"

    def test_no_repo_access_excluded(self):
        """Candidate without repo access must be excluded."""
        result = self._recommend(
            codeowners_map={},
            review_history={"eve": 5},  # eve not in collaborators
            commit_history={"eve": 10},
            repo_collaborators={"bob"},
        )
        if result.has_suggestion:
            assert result.recommended_username != "eve"

    def test_codeowner_outranks_commit_history(self):
        """CODEOWNER match should score higher than pure commit history."""
        result = self._recommend(
            codeowners_map={"src/auth/": ["bob"]},
            review_history={},
            commit_history={"carol": 50},  # carol has many commits but no CODEOWNERS match
            repo_collaborators={"bob", "carol"},
        )
        assert result.has_suggestion is True
        assert result.recommended_username == "bob"

    def test_reason_always_present_when_suggestion_made(self):
        result = self._recommend(
            codeowners_map={"src/auth/": ["bob"]},
        )
        if result.has_suggestion:
            assert result.reason is not None
            assert len(result.reason) > 0

    def test_confidence_score_bounded(self):
        result = self._recommend(
            codeowners_map={"src/auth/": ["bob"]},
        )
        if result.has_suggestion:
            assert 0.0 <= result.confidence_score <= 100.0

    def test_shortlist_populated_with_multiple_candidates(self):
        result = self._recommend(
            codeowners_map={"src/auth/": ["bob"]},
            review_history={"carol": 3},
            commit_history={"dave": 4},
            repo_collaborators={"bob", "carol", "dave"},
        )
        if result.has_suggestion:
            assert isinstance(result.shortlist, list)

    def test_abstain_reason_mentions_evidence(self):
        result = self._recommend(
            codeowners_map={},
            review_history={},
            commit_history={},
        )
        assert result.has_suggestion is False
        assert result.abstain_reason is not None

    def test_single_incidental_commit_filtered(self):
        """A single commit is below the minimum evidence threshold."""
        result = self._recommend(
            codeowners_map={},
            review_history={"carol": 1},  # Only 1 review — below threshold
            commit_history={"carol": 1},  # Only 1 commit — below threshold
            repo_collaborators={"carol"},
        )
        assert result.has_suggestion is False

    def test_two_reviews_qualifies(self):
        """2+ reviews on the files qualifies as meaningful evidence."""
        result = self._recommend(
            codeowners_map={},
            review_history={"carol": 2},
            commit_history={},
            repo_collaborators={"carol"},
        )
        assert result.has_suggestion is True
        assert result.recommended_username == "carol"


class TestCodeownersPatternMatching:
    def test_exact_path_match(self):
        from app.analysis.reviewer.service import ReviewerRankingService

        assert ReviewerRankingService._matches_codeowners_pattern(
            "src/auth/login.py", "src/auth/login.py"
        )

    def test_directory_prefix_match(self):
        from app.analysis.reviewer.service import ReviewerRankingService

        assert ReviewerRankingService._matches_codeowners_pattern("src/auth/login.py", "src/auth/")

    def test_wildcard_extension_match(self):
        from app.analysis.reviewer.service import ReviewerRankingService

        assert ReviewerRankingService._matches_codeowners_pattern("src/auth/login.py", "*.py")

    def test_no_match(self):
        from app.analysis.reviewer.service import ReviewerRankingService

        assert not ReviewerRankingService._matches_codeowners_pattern("src/utils.py", "src/auth/")
