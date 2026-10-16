"""Compatibility adapters for existing imports."""
from research.engine import research_topic
from research.trend_finder import build_research_queries, search_public_web
from research.idea_scoring import score_idea, rank_candidates
__all__ = ["research_topic", "build_research_queries", "search_public_web", "score_idea", "rank_candidates"]
