"""Backward-compatible imports for the render module."""
from .render_video import RenderError, render_video, validate_video, analyze_black_and_silence
__all__ = ["RenderError", "render_video", "validate_video", "analyze_black_and_silence"]
