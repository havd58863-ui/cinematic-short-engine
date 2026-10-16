"""Compatibility wrapper around the canonical research scoring module."""
from research.idea_scoring import score_idea, rank_candidates, rank_topic_results
__all__ = ["score_idea", "rank_candidates", "rank_topic_results"]
