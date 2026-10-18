"""Scriptwriting adapter: reuse a configured existing writer first, else OmniRoute API."""
from __future__ import annotations
import json
import os
import shlex
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

class ScriptwriterUnavailable(RuntimeError):
    pass


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


def _run_omniroute_gateway(prompt: str, api_key: str, base_url: str | None, model: str | None, timeout: int) -> str:
    endpoint = (base_url or "https://omniroute.online/v1/chat/completions").rstrip("/")
    selected_model = model or os.getenv("OMNIROUTE_MODEL", "gpt-4o-mini")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = json.dumps({
        "model": selected_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.65
    }).encode("utf-8")
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        choices = data.get("choices", [])
        if choices and len(choices) > 0:
            content = choices[0].get("message", {}).get("content", "").strip()
            if content:
                return content
        raise ScriptwriterUnavailable("OmniRoute gateway returned empty response choices.")
    except ScriptwriterUnavailable:
        raise
    except Exception as exc:
        raise ScriptwriterUnavailable(f"OmniRoute request failed: {type(exc).__name__}: {exc}") from exc


def generate_text(prompt: str, output_path: str | Path | None = None, model: str | None = None, timeout: int = 600) -> str:
    """Routes LLM generation requests: SCRIPTWRITER_COMMAND -> OmniRoute Gateway."""
    command = os.getenv("SCRIPTWRITER_COMMAND", "").strip()
    omniroute_key = os.getenv("OMNIROUTE_API_KEY", "").strip()

    if command:
        result = _run_configured_command(command, prompt, timeout)
    elif omniroute_key:
        omniroute_url = os.getenv("OMNIROUTE_BASE_URL", "https://omniroute.online/v1/chat/completions")
        result = _run_omniroute_gateway(prompt, omniroute_key, omniroute_url, model, timeout)
    else:
        raise ScriptwriterUnavailable("OmniRoute API key not configured (OMNIROUTE_API_KEY is missing).")

    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result + "\n", encoding="utf-8")
    return result


def _build_fallback_script(topic: str, sources: list[dict[str, Any]], seconds: int = 45) -> str:
    """Build a deterministic, schema-compliant TikTok script when LLM services are unavailable."""
    clean_topic = topic.strip().rstrip(".!?")
    if not clean_topic:
        clean_topic = "this viral phenomenon"

    extracted_facts = []
    for s in sources[:5]:
        text = (s.get("snippet") or s.get("extracted_text") or s.get("title") or "").strip()
        if text and text not in extracted_facts:
            first_clause = text.split(".")[0].strip()
            if len(first_clause) > 10:
                extracted_facts.append(first_clause)

    hook = f"Here is what nobody tells you about {clean_topic}."
    conflict = f"Most people assume it's simple, but the reality behind {clean_topic} is far more surprising."

    if extracted_facts:
        fact_1 = extracted_facts[0].rstrip(".") + "."
        fact_2 = (extracted_facts[1].rstrip(".") + ".") if len(extracted_facts) > 1 else f"This completely changes how we understand {clean_topic}."
        context = f"Research reveals that {fact_1} {fact_2}"
    else:
        context = f"When you look closely at the underlying patterns of {clean_topic}, critical details emerge that challenge standard assumptions."

    payoff = f"Ultimately, understanding {clean_topic} comes down to recognizing these fundamental dynamics and their real-world impact."
    cta = "Save this for later and share your thoughts in the comments."

    paragraphs = [hook, conflict, context, payoff, cta]
    return "\n\n".join(paragraphs)


def write_script(topic: str, sources: list[dict[str, Any]], seconds: int = 45, model: str | None = None) -> str:
    try:
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
        res = generate_text(prompt, model=model).strip()
        if res:
            return res
    except ScriptwriterUnavailable:
        pass

    return _build_fallback_script(topic, sources, seconds=seconds)


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
