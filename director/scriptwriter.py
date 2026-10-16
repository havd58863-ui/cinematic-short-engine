"""Backward-compatible module; canonical implementation is scriptwriter_adapter.py."""
from .scriptwriter_adapter import ScriptwriterUnavailable, generate_text, write_script
from .script_analysis import estimate_duration_seconds
__all__ = ["ScriptwriterUnavailable", "generate_text", "write_script", "estimate_duration_seconds"]
