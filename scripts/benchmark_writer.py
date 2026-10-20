#!/usr/bin/env python3
"""Writing-model acceptance gate harness.

Runs three fixed, DNA-derived tasks against one Ollama model and records
hard metrics + readable samples. Stdlib only, so it runs anywhere Python 3.12 does.

Tasks (identical prompts/seeds for every candidate = fair, blind-comparable gate):
  T1  writer / account_01 psychology  -> strict JSON, DNA structure, temp 0.8
  T2  writer / account_02 storytelling -> strict JSON, DNA progression, temp 0.8
  T3  retention_editor on a fixed weak draft -> strict JSON with WHYs, temp 0.35

Exit codes: 0 = gate data collected (quality may still be poor; humans score it)
            2 = infrastructure failure (cannot reach/pull/serve the model)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

NS = 1_000_000_000
SEED = 20261020
BANNED = ["dark psychology", "mind control", "like and subscribe", "in this video"]

# ---------------------------------------------------------------- tasks ----

T1_SYSTEM = """You are the script director for "Cinematic Psychology", a premium short-form channel.
Core promise: make the viewer recognize themselves before they realize they are learning.
Rules: natural neutral international English; poetic, intimate, precise; NO 'dark psychology tricks',
no mind-control promises, no fake certainty; never diagnose the viewer or another person;
phrase mechanisms proportionally ("often", "can"); build tension through the unexplained;
end with a useful reframe. Voice: male, deep, controlled, revealing a realization privately.
Write spoken lines only — short sentences that breathe. The hook must land in under 3 seconds."""

T1_USER = (
    "Brief (social behavior pillar): why silence from someone you care about feels louder than words.\n"
    "Write a 150-230 word spoken script with the exact locked structure.\n"
    "hook: one line, at most 12 words, from hook_family you choose.\n"
    "visual_metaphor: one line — a cinematic scene that EMBODIES the mental state, "
    "never literally illustrates the words.\n"
    "Return only the JSON object."
)

T1_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook_family": {
            "type": "string",
            "enum": ["recognition", "contradiction", "warning", "question", "observation"],
        },
        "hook": {"type": "string"},
        "curiosity": {"type": "string"},
        "psychological_mechanism": {"type": "string"},
        "realization": {"type": "string"},
        "final_line": {"type": "string"},
        "visual_metaphor": {"type": "string"},
    },
    "required": [
        "title", "hook_family", "hook", "curiosity", "psychological_mechanism",
        "realization", "final_line", "visual_metaphor",
    ],
    "additionalProperties": False,
}
T1_SPOKEN = ["hook", "curiosity", "psychological_mechanism", "realization", "final_line"]

T2_SYSTEM = """You are the script director for "Cinematic Nostalgic Storytelling".
Identity: stories children can love — and adults can remember. Emotional core: wonder and nostalgia.
Family viewing without becoming preschool-only. Every story leaves a question, feeling, image,
or memory after the final shot. World: cinematic storybook realism — tactile, believable, gentle wonder.
Voice: male, warm, deep, literary storyteller; tender, never melodramatic. Golden practical light,
snow, steam and distant sounds may breathe between lines. No psychology lesson, no moral lecture."""

T2_USER = (
    "Brief: world = a small railway station with a steam train in a snowy village, winter night.\n"
    'Opening in the spirit of: "The old station had been closed for decades. Until one winter night..."\n'
    "Premise seed (develop freely, stay emotionally true): a train that has not stopped here for "
    "thirty years\n"
    "arrives carrying exactly one passenger. Total spoken narration across all beats: "
    "190-300 words (about 75-120 seconds).\n"
    "hero_shot: one line describing the single strongest cinematic image of the piece.\n"
    "Return only the JSON object."
)

T2_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "world": {"type": "string"},
        "cold_open": {"type": "string"},
        "question": {"type": "string"},
        "journey": {"type": "string"},
        "discovery": {"type": "string"},
        "emotional_turn": {"type": "string"},
        "payoff": {"type": "string"},
        "after_image": {"type": "string"},
        "hero_shot": {"type": "string"},
    },
    "required": [
        "title", "world", "cold_open", "question", "journey",
        "discovery", "emotional_turn", "payoff", "after_image", "hero_shot",
    ],
    "additionalProperties": False,
}
T2_SPOKEN = ["cold_open", "question", "journey", "discovery", "emotional_turn", "payoff", "after_image"]

WEAK_DRAFT = """In this video, we will talk about the psychology of why people do not reply to your messages.
Psychology is a very interesting science that studies the human mind and behaviour in many different ways.
When someone does not reply, it can mean many things, like they are busy or they forgot or they are angry.
Studies show that communication is important for relationships and for mental health in general.
So you should not worry too much, because most of the time it is probably nothing serious at all.
But sometimes people use silence because they need space, and that is also a normal thing in life.
The important thing is to communicate well and to be patient with the people around you every day.
That is all for today. remember to be kind, and do not forget to like and subscribe for more psychology."""

T3_SYSTEM = (
    'You are the retention editor for "Cinematic Psychology" '
    "(second-pass role, you did NOT write the draft).\n"
    "Your law: hook lands in <=3 seconds; open a loop the viewer must close; "
    "renew curiosity every 3-6 seconds;\n"
    "one midpoint turn; final line that sticks. Natural neutral international English, poetic and precise.\n"
    "No 'dark psychology tricks', no diagnosis of the viewer, no fake certainty, no calls to action.\n"
    "You must justify every meaningful edit with a concrete why, and score your own result honestly (0-10)."
)

T3_USER = (
    "Rewrite this weak draft into the locked structure (150-230 spoken words total).\n"
    "Keep the same topic: unanswered messages and the weight of silence.\n"
    "\n"
    "DRAFT:\n"
    f'"""{WEAK_DRAFT}"""\n'
    "\n"
    'Return only the JSON object. In "edits", list 4-7 meaningful changes: where, '
    "what you changed, and why it retains better."
)

T3_SCHEMA = {
    "type": "object",
    "properties": {
        "revised_script": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in T1_SPOKEN},
            "required": T1_SPOKEN,
            "additionalProperties": False,
        },
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "where": {"type": "string"},
                    "change": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["where", "change", "why"],
                "additionalProperties": False,
            },
        },
        "self_scores": {
            "type": "object",
            "properties": {
                k: {"type": "integer"}
                for k in ["hook_strength", "open_loop", "midpoint_turn", "final_line_stick"]
            },
            "required": ["hook_strength", "open_loop", "midpoint_turn", "final_line_stick"],
            "additionalProperties": False,
        },
    },
    "required": ["revised_script", "edits", "self_scores"],
    "additionalProperties": False,
}

TASKS = [
    {"id": "t1_writer_psychology", "system": T1_SYSTEM, "user": T1_USER, "schema": T1_SCHEMA,
     "spoken": T1_SPOKEN, "temperature": 0.8, "words": (150, 230), "num_predict": 1100},
    {"id": "t2_writer_storytelling", "system": T2_SYSTEM, "user": T2_USER, "schema": T2_SCHEMA,
     "spoken": T2_SPOKEN, "temperature": 0.8, "words": (190, 300), "num_predict": 1300},
    {"id": "t3_retention_editor", "system": T3_SYSTEM, "user": T3_USER, "schema": T3_SCHEMA,
     "spoken": None, "temperature": 0.35, "words": (150, 230), "num_predict": 1500},
]

# ------------------------------------------------------------- http utils --


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 1800) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def http_stream_lines(url: str, payload: dict, timeout: int = 3600):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if line:
                yield json.loads(line.decode())


# --------------------------------------------------------------- analysis --


def words(text: str) -> int:
    return len(re.findall(r"[^\s]+", text))


def english_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    en = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return round(en / len(letters), 3)


def repetition_ratio(text: str) -> float:
    sentences = [s.strip().lower() for s in re.split(r"[.!?]+", text) if len(s.strip()) > 12]
    if not sentences:
        return 0.0
    return round(1 - len(set(sentences)) / len(sentences), 3)


def analyze(task: dict, obj: dict) -> dict:
    if task["id"] == "t3_retention_editor":
        script = obj.get("revised_script", {}) if isinstance(obj.get("revised_script"), dict) else {}
        spoken_keys, spoken_text = T1_SPOKEN, " ".join(str(script.get(k, "")) for k in T1_SPOKEN)
        edits = obj.get("edits", []) if isinstance(obj.get("edits"), list) else []
        extra = {
            "edits_count": len(edits),
            "edits_all_have_why": bool(edits)
            and all(str(e.get("why", "")).strip() for e in edits if isinstance(e, dict)),
            "hook_words": words(str(script.get("hook", ""))),
        }
    else:
        spoken_keys = task["spoken"]
        spoken_text = " ".join(str(obj.get(k, "")) for k in spoken_keys)
        extra = {"hook_words": words(str(obj.get(spoken_keys[0], "")))}
    lower = spoken_text.lower()
    lo, hi = task["words"]
    script_obj = obj if task["id"] != "t3_retention_editor" else obj.get("revised_script", {})
    empty = [k for k in spoken_keys if not str(script_obj.get(k, "")).strip()]
    return {
        "spoken_words": words(spoken_text),
        "words_in_range": lo <= words(spoken_text) <= hi,
        "english_ratio": english_ratio(spoken_text),
        "repetition_ratio": repetition_ratio(spoken_text),
        "banned_phrases_found": [b for b in BANNED if b in lower],
        "empty_spoken_fields": empty,
        **extra,
    }


# ------------------------------------------------------------------- run ---


def chat(base: str, model: str, messages: list, schema: dict, temperature: float, num_predict: int) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": temperature, "seed": SEED, "num_ctx": 8192, "num_predict": num_predict},
    }
    return http_json("POST", f"{base}/api/chat", body, timeout=2700)


def run_task(base: str, model: str, task: dict, raw_dir: pathlib.Path) -> dict:
    messages = [{"role": "system", "content": task["system"]}, {"role": "user", "content": task["user"]}]
    attempts, obj, last_err = [], None, None
    for n in (1, 2):  # models.yaml: bounded retries (2 total attempts recorded here)
        t0 = time.time()
        resp = chat(base, model, messages, task["schema"], task["temperature"], task["num_predict"])
        wall = round(time.time() - t0, 2)
        content = (resp.get("message") or {}).get("content", "")
        (raw_dir / f"{task['id']}_attempt{n}.json").write_text(
            json.dumps(resp, ensure_ascii=False, indent=1), encoding="utf-8")
        ev, dur = resp.get("eval_count") or 0, resp.get("eval_duration") or 0
        record = {
            "attempt": n, "wall_seconds": wall,
            "total_seconds": round((resp.get("total_duration") or 0) / NS, 2),
            "load_seconds": round((resp.get("load_duration") or 0) / NS, 2),
            "prompt_tokens": resp.get("prompt_eval_count"),
            "eval_tokens": ev,
            "eval_tokens_per_second": round(ev / (dur / NS), 2) if dur else None,
            "done_reason": resp.get("done_reason"),
        }
        try:
            obj = json.loads(content)
            record["json_valid"] = True
            attempts.append(record)
            break
        except Exception as exc:  # noqa: BLE001 - recorded, then one bounded retry
            last_err = f"{type(exc).__name__}: {exc}"
            record.update({"json_valid": False, "json_error": last_err, "content_preview": content[:240]})
            attempts.append(record)
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "That was not valid JSON for the required schema. "
                                            "Return ONLY the corrected JSON object, no prose."},
            ]
    result = {"task": task["id"], "temperature": task["temperature"], "seed": SEED,
              "attempts": attempts, "json_valid": obj is not None, "output": obj}
    if obj is not None:
        result["checks"] = analyze(task, obj)
    elif last_err:
        result["error"] = last_err
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", required=True)
    p.add_argument("--out", required=True, type=pathlib.Path)
    p.add_argument("--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    raw_dir = args.out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {"model": args.model, "base_url": base, "seed": SEED, "tasks": []}
    try:
        report["ollama_version"] = http_json("GET", f"{base}/api/version", timeout=20).get("version")
    except Exception as exc:  # noqa: BLE001
        print(f"::error::Ollama not reachable at {base}: {exc}")
        return 2

    print(f"== pull {args.model} ==", flush=True)
    t0 = time.time()
    try:
        last = None
        for line in http_stream_lines(f"{base}/api/pull", {"model": args.model, "stream": True}):
            last = line
            if line.get("error"):
                raise RuntimeError(str(line["error"]))
        if not last or last.get("status") not in ("success", None):
            print(f"pull ended with: {last}")
    except Exception as exc:  # noqa: BLE001
        print(f"::error::pull failed: {exc}")
        return 2
    report["pull_seconds"] = round(time.time() - t0, 1)

    tags = http_json("GET", f"{base}/api/tags", timeout=60).get("models", [])
    mine = next((m for m in tags if m.get("name") == args.model or m.get("model") == args.model), None)
    if mine:
        report.update({"digest": mine.get("digest"), "size_gb": round((mine.get("size") or 0) / 1e9, 2),
                       "parameter_size": (mine.get("details") or {}).get("parameter_size"),
                       "quantization": (mine.get("details") or {}).get("quantization_level")})

    for task in TASKS:
        print(f"== {task['id']} ==", flush=True)
        try:
            report["tasks"].append(run_task(base, args.model, task, raw_dir))
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"::error::task {task['id']} transport failure: {exc}")
            report["tasks"].append({"task": task["id"], "json_valid": False, "error": f"transport: {exc}"})

    try:
        ps = http_json("GET", f"{base}/api/ps", timeout=30).get("models", [])
        if ps:
            report["loaded_size_gb"] = round((ps[0].get("size") or 0) / 1e9, 2)
        pass
    except Exception:  # noqa: BLE001 - metric is best-effort
        pass

    (args.out / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    with (args.out / "samples.md").open("w", encoding="utf-8") as f:
        f.write(
            f"# Writing gate — {args.model}\n\n"
            f"digest: `{report.get('digest')}` · size {report.get('size_gb')} GB"
            f" · loaded {report.get('loaded_size_gb')} GB"
            f" · pull {report.get('pull_seconds')}s · ollama {report.get('ollama_version')}\n"
        )
        for r in report["tasks"]:
            f.write(f"\n---\n\n## {r['task']}  (json_valid={r.get('json_valid')})\n\n")
            if r.get("checks"):
                f.write("checks: " + json.dumps(r["checks"], ensure_ascii=False) + "\n\n")
            out = r.get("output")
            if isinstance(out, dict):
                script = out.get("revised_script", out)
                for k, v in script.items():
                    f.write(f"**{k}:** {v}\n\n")
                if out.get("edits"):
                    edit_lines = "\n".join(
                        f"- [{e.get('where')}] {e.get('change')} — why: {e.get('why')}" for e in out["edits"]
                    )
                    f.write("**edits:**\n\n" + edit_lines + "\n\n")
                if out.get("self_scores"):
                    f.write("self_scores: " + json.dumps(out["self_scores"]) + "\n")
            else:
                f.write(f"(no valid JSON output; error: {r.get('error')})\n")
            for a in r.get("attempts", []):
                f.write(
                    f"\n`attempt {a['attempt']}: {a.get('eval_tokens')} tok"
                    f" @ {a.get('eval_tokens_per_second')} tok/s,"
                    f" wall {a.get('wall_seconds')}s, done={a.get('done_reason')}`\n"
                )
    print(f"== done: {args.out} ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
