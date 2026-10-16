"""Compatibility wrapper for the canonical scriptwriter adapter."""
from director.scriptwriter_adapter import ScriptwriterUnavailable, generate_text, write_script
from director.script_analysis import estimate_duration_seconds
__all__ = ["ScriptwriterUnavailable", "generate_text", "write_script", "estimate_duration_seconds"]
