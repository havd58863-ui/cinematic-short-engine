"""Scriptwriting adapter: reuse a configured existing writer first, else Ollama."""
from __future__ import annotations
import json
import os
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

class ScriptwriterUnavailable(RuntimeError):
    pass


def ollama_is_ready(base_url: str | None = None, timeout: float = 2.0) -> bool:
    base = (base_url or os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _run_configured_command(command: str, prompt: str, timeout: int) -> str:
    with tempfile.TemporaryDirectory(prefix="tiktok_writer_") as td:
        prompt_file = Path(td) / "prompt.txt"
        output_file = Path(td) / "output.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        args = shlex.split(command) + ["--prompt-file", str(prompt_file), "--output-file", str(output_file)]
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        except Exception as exc:
            raise ScriptwriterUnavailable(f"Configured scriptwriter command could not run: {type(exc).__name__}: {exc}") from exc
        if proc.returncode != 0:
            raise ScriptwriterUnavailable(f"Configured scriptwriter exited {proc.returncode}: {(proc.stderr or proc.stdout)[-2000:]}")
        result = output_file.read_text(encoding="utf-8").strip() if output_file.exists() else (proc.stdout or "").strip()
        if not result:
            raise ScriptwriterUnavailable("Configured scriptwriter returned an empty result.")
        return result


def generate_text(prompt: str, output_path: str | Path | None = None, model: str | None = None, timeout: int = 600) -> str:
    """Call the pre-existing writer command if configured; otherwise call Ollama's HTTP API.

    SCRIPTWRITER_COMMAND contract: executable + args, then --prompt-file PATH --output-file PATH.
    This allows a repository-specific scriptwriter to be reused without assuming its API.
    """
    command = os.getenv("SCRIPTWRITER_COMMAND", "").strip()
    if command:
        result = _run_configured_command(command, prompt, timeout)
    else:
        base = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        selected_model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")
        payload = json.dumps({"model": selected_model, "prompt": prompt, "stream": False, "options": {"temperature": 0.65, "num_ctx": 8192}}).encode("utf-8")
        request = urllib.request.Request(base + "/api/generate", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            result = str(data.get("response", "")).strip()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[-1200:]
            raise ScriptwriterUnavailable(f"Ollama request failed ({exc.code}): {body}. Verify the service and pull {selected_model}.") from exc
        except Exception as exc:
            raise ScriptwriterUnavailable(f"Ollama is unreachable at {base}: {type(exc).__name__}: {exc}. Start Ollama and pull {selected_model}, or configure SCRIPTWRITER_COMMAND.") from exc
        if not result:
            raise ScriptwriterUnavailable(f"Ollama model {selected_model} returned no text.")
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result + "\n", encoding="utf-8")
    return result


def write_script(topic: str, sources: list[dict[str, Any]], seconds: int = 45, model: str | None = None) -> str:
    evidence = "\n".join(
        f"[{index}] {s.get('title','(untitled)')}\nURL: {s.get('url','')}\nDate: {s.get('published_at') or 'not available'}\nEvidence: {s.get('extracted_text') or s.get('snippet','')}"
        for index, s in enumerate(sources[:10], 1)
    ) or "No source text was retrieved. Do not make externally verifiable factual claims; frame claims as questions or omit them."
    prompt = f"""You are an experienced American English TikTok writer and story editor.
Write a coherent spoken script targeting {seconds} seconds for US viewers.
TOPIC: {topic}
RESEARCH EVIDENCE (use only supported factual claims; include no fake citations):
{evidence}

STRUCTURE:
- First sentence is a compelling hook usable within 1-2 seconds.
- State a clear question, promise, conflict, or surprising premise.
- Give the minimum context needed.
- Escalate through connected beats; each beat should change what the viewer understands.
- Use concrete details and visualizable actions rather than filler.
- Deliver a genuine payoff or resolution that follows from the setup.
- End with a natural CTA only if it fits.

Write fluent, natural American English. Do not add a generic intro, fabricate metrics, invent quotes or facts, repeat the hook, or write disconnected cinematic fragments. Use paragraph breaks for narration beats. Return only the script, not analysis or shot prompts."""
    return generate_text(prompt, model=model).strip()


def generate_structured_json(prompt: str, model: str | None = None) -> dict[str, Any]:
    raw = generate_text(prompt, model=model)
    # Find the first balanced JSON object, ignoring braces inside quoted strings.
    start = raw.find("{")
    if start < 0:
        raise ScriptwriterUnavailable("Director returned no JSON object.")
    in_string = False
    escaped = False
    depth = 0
    end = None
    for i in range(start, len(raw)):
        char = raw[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ScriptwriterUnavailable("Director response contained incomplete JSON.")
    try:
        result = json.loads(raw[start:end])
    except json.JSONDecodeError as exc:
        raise ScriptwriterUnavailable(f"Director JSON could not be parsed: {exc}") from exc
    if not isinstance(result, dict):
        raise ScriptwriterUnavailable("Director JSON root must be an object.")
    return result
