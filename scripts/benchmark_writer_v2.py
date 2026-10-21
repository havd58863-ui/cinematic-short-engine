#!/usr/bin/env python3
"""Writing-model acceptance gate — ROUND 2 harness.

One invocation = one job cell: (model x account x task_type) over every topic
and paired seed from config/writing_gate.yaml. Each generation is validated by
engine.validation (the SAME module production will use); failures receive up to
N targeted repairs whose prompts carry the validator's named issues. Terminal
states are passed_validation / failed_validation — nothing is silently waived.

Run with PYTHONPATH=src (the workflow sets it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import statistics
import sys
import time
import urllib.error
import urllib.request

import yaml

from engine.contracts import AccountId
from engine.validation import (
    BeatBudget,
    ScriptConstraints,
    ValidationReport,
    ValidationStatus,
    validate_editor_extras,
    validate_script,
)

NS = 1_000_000_000
PSYCH_SPOKEN = ["hook", "curiosity", "psychological_mechanism", "realization", "final_line"]
STORY_SPOKEN = ["cold_open", "question", "journey", "discovery", "emotional_turn", "payoff", "after_image"]
PSYCH_SCORES = ["hook_strength", "open_loop", "midpoint_turn", "final_line_stick"]
STORY_SCORES = ["curiosity_hold", "midpoint_turn", "payoff_resolution", "final_image_stick"]
NUM_PREDICT = {("write", "account_01_psychology"): 1300, ("write", "account_02_storytelling"): 1600,
               ("edit", "account_01_psychology"): 1700, ("edit", "account_02_storytelling"): 1900}

_PSYCH_WRITE_SYSTEM = (
    "You are the script director for \"Cinematic Psychology\", a premium short-form channel.\n"
    "Core promise: make the viewer recognize themselves before they realize they are learning.\n"
    "Rules: natural neutral international English; poetic, intimate, precise; NO 'dark psychology "
    "tricks',\n"
    "no mind-control promises, no fake certainty; never diagnose the viewer or another person;\n"
    "phrase mechanisms proportionally (\"often\", \"can\"); build tension through the unexplained;\n"
    "end with a useful reframe. Voice: male, deep, controlled, revealing a realization privately.\n"
    "Write spoken lines only — short sentences that breathe. The hook must land in under 3 seconds.\n"
    "Every spoken beat has a word budget below: fill each beat with its OWN new substance. Never\n"
    "restate another beat. Never claim \"research shows\" — interpret tentatively instead."
)

_STORY_WRITE_SYSTEM = (
    "You are the script director for \"Cinematic Nostalgic Storytelling\".\n"
    "Identity: stories children can love — and adults can remember. Emotional core: wonder and "
    "nostalgia.\n"
    "Family viewing without becoming preschool-only. Every story leaves a question, feeling, image,\n"
    "or memory after the final shot. World: cinematic storybook realism — tactile, believable, gentle "
    "wonder.\n"
    "Voice: male, warm, deep, literary storyteller; tender, never melodramatic. Golden practical "
    "light,\n"
    "snow, steam and distant sounds may breathe between lines. No psychology lesson, no moral "
    "lecture.\n"
    "Your narration is PERFORMED text only: never mention cameras, shots, cuts or scenes. Every clue "
    "you\n"
    "plant must either pay off or remain an intentional, felt mystery — the central question must "
    "earn\n"
    "an answer or a transformation by the payoff. Fill each beat to its word budget with its own "
    "events."
)

_PSYCH_EDIT_SYSTEM = (
    "You are the retention editor for \"Cinematic Psychology\" (second-pass role, you did NOT write the "
    "draft).\n"
    "Your law: hook lands in <=3 seconds; open a loop the viewer must close; renew curiosity every 3-6 "
    "seconds;\n"
    "one midpoint turn; final line that sticks. Natural neutral international English, poetic and "
    "precise.\n"
    "No 'dark psychology tricks', no diagnosis of the viewer or of other people, no fake certainty, "
    "no\n"
    "\"research shows\" claims, no calls to action. First diagnose the draft's flaws, then REBUILD it "
    "into the\n"
    "locked structure hitting every word budget. Justify every meaningful edit: the flaw, your "
    "change,\n"
    "and why it repairs retention. Score your own result honestly (0-10)."
)

_STORY_EDIT_SYSTEM = (
    "You are the story retention editor for \"Cinematic Nostalgic Storytelling\" (you did NOT write the "
    "draft).\n"
    "Rebuild weak drafts into the locked progression: cold_open, question, journey, discovery,\n"
    "emotional_turn, payoff, after_image. Rules: the central question must receive a payoff or an\n"
    "earned transformation; every planted clue must connect; narration is performed story text ONLY —\n"
    "remove any camera or stage directions from the draft; family-warm literary English, tender never\n"
    "melodramatic; no psychology lecture, no moral at the end. Hit every word budget with real "
    "events.\n"
    "Justify every meaningful edit: the flaw, your change, why it repairs the story. Honest self-scores "
    "(0-10)."
)

SYSTEMS = {
    ("account_01_psychology", "write"): _PSYCH_WRITE_SYSTEM,
    ("account_02_storytelling", "write"): _STORY_WRITE_SYSTEM,
    ("account_01_psychology", "edit"): _PSYCH_EDIT_SYSTEM,
    ("account_02_storytelling", "edit"): _STORY_EDIT_SYSTEM,
}

WEAK_DRAFTS = {
    ("account_01_psychology", "psy_reread_messages"): (
        "In this video, we will talk about why people reread old messages on their phone. "
        "Messaging is a very common part of modern life and almost everyone does it every day. "
        "Research shows that rereading messages is a clear sign that a person is still in love. "
        "Sometimes people reread because they are bored, and sometimes because they miss the person. "
        "Both reasons are normal and there is nothing to worry about in most cases. "
        "The important thing is to live your life and not think too much about old chats. "
        "Time passes and feelings change, and that is just how life works for everyone. "
        "Thanks for watching, and do not forget to like and subscribe for more psychology facts."
    ),
    ("account_01_psychology", "psy_conflict_silence"): (
        "Today we explain people who go silent in arguments, and the truth is very simple. "
        "When your partner goes quiet, it always means they have stopped caring about you. "
        "This kind of person is clearly avoidant and is punishing you on purpose. "
        "Psychologists have found that silence in conflict is a form of control in every case. "
        "So if someone goes silent with you, you already know exactly what is inside their head. "
        "There is no other explanation and you should never doubt this fact. "
        "The solution is to demand an answer immediately until they finally talk to you. "
        "Follow this channel for more dark psychology facts about people around you."
    ),
    ("account_02_storytelling", "story_library_book"): (
        "The camera pans across the tall shelves of the old library while dust falls in the light. "
        "Cut to a close-up of a book with no title on its dark green cover. "
        "A woman returns this book to the desk, exactly like she did ten years ago. "
        "The librarian looks at her and thinks she looks exactly the same as before. "
        "The librarian looks at her and thinks she looks exactly the same as before. "
        "The woman smiles a little and walks out through the door into the street. "
        "Later the librarian puts the book back on the shelf and goes home for dinner. "
        "Winter is coming soon and the library will be quiet, like it always is in winter."
    ),
    ("account_02_storytelling", "story_lighthouse"): (
        "There is an old lighthouse near the sea and sometimes its light turns on at night. "
        "Actually this is not mysterious at all, because it is only the moon reflecting on the glass. "
        "The keeper of the lighthouse died many years ago and nobody works there now. "
        "When a storm comes, the waves are big and the wind makes a lot of noise outside. "
        "People in the village can see the light from far away when the weather is bad. "
        "A boy from the village watches the light and then goes back to his house to sleep. "
        "In the morning the storm is gone and everything is calm and normal again. The end."
    ),
}


def budget_lines(spec: ScriptConstraints) -> str:
    lines = [f"Word budgets (spoken text only; total {spec.total_words[0]}-{spec.total_words[1]} words):"]
    for field in spec.spoken_fields:
        budget = spec.beat_budgets.get(field)
        if budget:
            lines.append(f"- {field}: {budget.min_words}-{budget.max_words} words")
    return "\n".join(lines)


def writer_schema(account: AccountId) -> dict:
    string = {"type": "string"}
    if account is AccountId.PSYCHOLOGY:
        props = {"title": string, "hook_family": {"type": "string", "enum": [
            "recognition", "contradiction", "warning", "question", "observation"]}}
        props.update({k: string for k in PSYCH_SPOKEN})
        props["visual_metaphor"] = string
    else:
        props = {"title": string, "world": string}
        props.update({k: string for k in STORY_SPOKEN})
        props["hero_shot"] = string
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def editor_schema(account: AccountId) -> dict:
    string = {"type": "string"}
    spoken = PSYCH_SPOKEN if account is AccountId.PSYCHOLOGY else STORY_SPOKEN
    scores = PSYCH_SCORES if account is AccountId.PSYCHOLOGY else STORY_SCORES
    return {
        "type": "object",
        "properties": {
            "revised_script": {"type": "object", "properties": {k: string for k in spoken},
                               "required": spoken, "additionalProperties": False},
            "edits": {"type": "array", "minItems": 4, "maxItems": 7, "items": {
                "type": "object",
                "properties": {"where": string, "change": string, "why": string},
                "required": ["where", "change", "why"], "additionalProperties": False}},
            "self_scores": {"type": "object",
                            "properties": {k: {"type": "integer"} for k in scores},
                            "required": scores, "additionalProperties": False},
        },
        "required": ["revised_script", "edits", "self_scores"],
        "additionalProperties": False,
    }


def user_prompt(account: AccountId, task_type: str, topic: dict, spec: ScriptConstraints) -> str:
    budgets = budget_lines(spec)
    if task_type == "write":
        extra = (
            "visual_metaphor: one line — a scene that EMBODIES the mental state, never illustrates words."
            if account is AccountId.PSYCHOLOGY
            else ("hero_shot: one line — the single strongest cinematic image; "
                  "it must differ from after_image.")
        )
        return (
            f"Brief: {topic['brief']}\n\n{budgets}\n{extra}\n"
            "Write the complete spoken script in the locked structure. Return only the JSON object."
        )
    draft = WEAK_DRAFTS[(account.value, topic["id"])]
    return (
        f"Same topic: {topic['brief']}\n\n{budgets}\n\n"
        f'WEAK DRAFT TO REBUILD:\n"""{draft}"""\n\n'
        "Return only the JSON object. In 'edits', list 4-7 meaningful changes: where, what you "
        "changed, and why it repairs a named flaw."
    )


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 2700) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def http_stream_lines(url: str, payload: dict, timeout: int = 3600):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            if line.strip():
                yield json.loads(line.decode())


def chat(base: str, model: str, messages: list, schema: dict, temperature: float,
         seed: int, num_ctx: int, num_predict: int) -> dict:
    body = {"model": model, "messages": messages, "stream": False, "think": False,
            "format": schema,
            "options": {"temperature": temperature, "seed": seed,
                        "num_ctx": num_ctx, "num_predict": num_predict}}
    return http_json("POST", f"{base}/api/chat", body)


def repair_message(report: ValidationReport | None, parse_error: str | None) -> str:
    if parse_error:
        return (
            "Validator issues to fix:\n- SCHEMA_INVALID: your previous reply was not valid JSON "
            f"for the required schema ({parse_error}).\nReturn ONLY the complete corrected JSON "
            "object, obeying every word budget."
        )
    lines = ["Validator issues to fix (address every one; keep everything already valid):"]
    for issue in report.issues:  # type: ignore[union-attr]
        where = issue.field or "script"
        lines.append(f"- {issue.code} [{where}] expected {issue.expected}; actual {issue.actual}. "
                     f"{issue.repair_hint}")
    lines.append("Return ONLY the complete corrected JSON object (all fields, final form).")
    return "\n".join(lines)


def run_generation(base: str, model: str, account: AccountId, task_type: str, topic: dict,
                   seed: int, spec: ScriptConstraints, cfg: dict, raw_dir: pathlib.Path) -> dict:
    schema = editor_schema(account) if task_type == "edit" else writer_schema(account)
    system = SYSTEMS[(account.value, task_type)]
    user = user_prompt(account, task_type, topic, spec)
    temperature = cfg["generation"]["retention_editor" if task_type == "edit" else "writer"]["temperature"]
    num_predict = NUM_PREDICT[(task_type, account.value)]
    num_ctx = int(cfg["ollama"]["num_ctx"])
    repair_max = int(cfg["generation"]["repair_max_attempts"])
    script_field = "revised_script" if task_type == "edit" else None
    label = f"{topic['id']}_seed{seed}"

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    attempts: list[dict] = []
    obj: dict | None = None
    report: ValidationReport | None = None
    parse_error: str | None = None
    previous_content = ""
    started = time.perf_counter()
    accepted_at: float | None = None

    for n in range(1, repair_max + 2):
        t0 = time.perf_counter()
        resp = chat(base, model, messages, schema, temperature, seed, num_ctx, num_predict)
        wall = round(time.perf_counter() - t0, 2)
        content = (resp.get("message") or {}).get("content", "")
        previous_content = content
        (raw_dir / f"{label}_attempt{n}.json").write_text(
            json.dumps(resp, ensure_ascii=False, indent=1), encoding="utf-8")
        ev, dur = resp.get("eval_count") or 0, resp.get("eval_duration") or 0
        record = {"attempt": n, "kind": "initial" if n == 1 else "repair", "wall_seconds": wall,
                  "eval_tokens": ev,
                  "eval_tokens_per_second": round(ev / (dur / NS), 2) if dur else None,
                  "done_reason": resp.get("done_reason")}
        try:
            obj = json.loads(content)
            parse_error = None
        except Exception as exc:  # noqa: BLE001 - named and repaired, never hidden
            obj, parse_error = None, f"{type(exc).__name__}: {exc}"
            record.update({"json_valid": False, "validation_status": "failed_validation",
                           "issue_codes": ["SCHEMA_INVALID"]})
            attempts.append(record)
        if obj is not None:
            report = validate_script(obj, spec, script_field=script_field)
            if task_type == "edit":
                extras = validate_editor_extras(obj)
                if extras:
                    report = report.model_copy(update={
                        "issues": [*report.issues, *extras],
                        "status": ValidationStatus.REPAIR_REQUIRED})
            record.update({"json_valid": True, "validation_status": str(report.status),
                           "issue_codes": [str(i.code) for i in report.issues]})
            attempts.append(record)
            if report.status is ValidationStatus.PASSED:
                accepted_at = round(time.perf_counter() - started, 2)
                break
        if n <= repair_max:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": previous_content},
                {"role": "user", "content": repair_message(report, parse_error)},
            ]

    accepted = accepted_at is not None
    return {
        "account": account.value, "task_type": task_type, "topic_id": topic["id"], "seed": seed,
        "first_attempt_pass": bool(attempts and attempts[0].get("validation_status") == "passed_validation"),
        "final_status": "passed_validation" if accepted else "failed_validation",
        "time_to_acceptable_seconds": accepted_at,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "attempts": attempts,
        "final_validation": report.model_dump(mode="json") if report else None,
        "output": obj,
    }


def make_spec(cfg: dict, account: AccountId, task_type: str) -> ScriptConstraints:
    raw = cfg["constraints"][account.value]
    shared = cfg["constraints"]["shared"]
    spoken = PSYCH_SPOKEN if account is AccountId.PSYCHOLOGY else STORY_SPOKEN
    if task_type == "edit":
        required = [*spoken, "edits", "self_scores"]
    elif account is AccountId.PSYCHOLOGY:
        required = [*spoken, "title", "hook_family", "visual_metaphor"]
    else:
        required = [*spoken, "title", "world", "hero_shot"]
    return ScriptConstraints(
        account=account,
        spoken_fields=spoken,
        required_fields=required,
        total_words=tuple(raw["total_words"]),
        beat_budgets={k: BeatBudget(min_words=v[0], max_words=v[1]) for k, v in raw["beat_budgets"].items()},
        hook_field=raw.get("hook_field"),
        hook_max_words=raw.get("hook_max_words"),
        must_differ=[tuple(pair) for pair in raw.get("must_differ", [])],
        **shared,
    )


def write_samples(path: pathlib.Path, model: str, meta: dict, generations: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# Writing gate R2 — {model} · {meta['account']} · {meta['task_type']}\n\n")
        f.write(f"digest `{meta.get('digest')}` · loaded {meta.get('loaded_size_gb')} GB · "
                f"ollama {meta.get('ollama_version')} · first-attempt pass "
                f"{meta.get('first_attempt_pass_rate')} · final acceptance "
                f"{meta.get('final_acceptance_rate')} · median time-to-acceptable "
                f"{meta.get('median_time_to_acceptable_seconds')}s\n")
        for gen in generations:
            f.write(f"\n---\n\n## {gen['topic_id']} · seed {gen['seed']} — {gen['final_status']}\n\n")
            out = gen.get("output")
            if isinstance(out, dict):
                script = out.get("revised_script", out)
                for key, value in script.items():
                    f.write(f"**{key}:** {value}\n\n")
                if out.get("edits"):
                    f.write("**edits:**\n\n" + "\n".join(
                        f"- [{e.get('where')}] {e.get('change')} — why: {e.get('why')}"
                        for e in out["edits"]) + "\n\n")
                if out.get("self_scores"):
                    f.write("self_scores: " + json.dumps(out["self_scores"]) + "\n")
            else:
                f.write("(no valid JSON ever produced)\n")
            final = gen.get("final_validation") or {}
            metrics = final.get("metrics") or {}
            issues = [i["code"] for i in (final.get("issues") or [])]
            f.write(f"\n`spoken_words={metrics.get('spoken_words')} hook_words={metrics.get('hook_words')}"
                    f" attempts={len(gen['attempts'])} tta={gen['time_to_acceptable_seconds']}s"
                    f" issues={issues}`\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--account", required=True, choices=[a.value for a in AccountId])
    parser.add_argument("--task-type", required=True, choices=["write", "edit"])
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--gate-config", type=pathlib.Path,
                        default=pathlib.Path("config/writing_gate.yaml"))
    parser.add_argument("--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    args = parser.parse_args()

    cfg = yaml.safe_load(args.gate_config.read_text(encoding="utf-8"))
    account = AccountId(args.account)
    spec = make_spec(cfg, account, args.task_type)
    raw_dir = args.out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")

    meta: dict = {"model": args.model, "account": args.account, "task_type": args.task_type,
                  "gate_config_sha256": hashlib.sha256(args.gate_config.read_bytes()).hexdigest(),
                  "generations": []}
    try:
        meta["ollama_version"] = http_json("GET", f"{base}/api/version", timeout=20).get("version")
    except Exception as exc:  # noqa: BLE001
        print(f"::error::Ollama not reachable at {base}: {exc}")
        return 2

    print(f"== pull {args.model} ==", flush=True)
    t0 = time.time()
    try:
        for line in http_stream_lines(f"{base}/api/pull", {"model": args.model, "stream": True}):
            if line.get("error"):
                raise RuntimeError(str(line["error"]))
    except Exception as exc:  # noqa: BLE001
        print(f"::error::pull failed: {exc}")
        return 2
    meta["pull_seconds"] = round(time.time() - t0, 1)
    tags = http_json("GET", f"{base}/api/tags", timeout=60).get("models", [])
    mine = next((m for m in tags if m.get("name") == args.model or m.get("model") == args.model), None)
    if mine:
        meta.update({"digest": mine.get("digest"),
                     "size_gb": round((mine.get("size") or 0) / 1e9, 2)})

    topics = cfg["topics"][args.account]
    seeds = [int(s) for s in cfg["generation"]["seeds_paired"]]
    for topic in topics:
        for seed in seeds:
            print(f"== {topic['id']} seed {seed} ==", flush=True)
            try:
                gen = run_generation(base, args.model, account, args.task_type,
                                     topic, seed, spec, cfg, raw_dir)
            except (urllib.error.URLError, TimeoutError) as exc:
                print(f"::error::transport failure {topic['id']} seed {seed}: {exc}")
                gen = {"account": args.account, "task_type": args.task_type,
                       "topic_id": topic["id"], "seed": seed, "first_attempt_pass": False,
                       "final_status": "failed_validation", "time_to_acceptable_seconds": None,
                       "attempts": [], "final_validation": None, "output": None,
                       "error": f"transport: {exc}"}
            meta["generations"].append(gen)
            print(f"   -> {gen['final_status']} tta={gen['time_to_acceptable_seconds']}", flush=True)

    gens = meta["generations"]
    ttas = [g["time_to_acceptable_seconds"] for g in gens if g["time_to_acceptable_seconds"] is not None]
    meta["first_attempt_pass_rate"] = round(sum(g["first_attempt_pass"] for g in gens) / len(gens), 3)
    meta["final_acceptance_rate"] = round(
        sum(g["final_status"] == "passed_validation" for g in gens) / len(gens), 3)
    meta["median_time_to_acceptable_seconds"] = round(statistics.median(ttas), 2) if ttas else None
    try:
        ps = http_json("GET", f"{base}/api/ps", timeout=30).get("models", [])
        if ps:
            meta["loaded_size_gb"] = round((ps[0].get("size") or 0) / 1e9, 2)
    except Exception:  # noqa: BLE001 - best-effort metric
        pass

    (args.out / "metrics.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    write_samples(args.out / "samples.md", args.model, meta, gens)
    print(f"== done {args.out}: first={meta['first_attempt_pass_rate']} "
          f"final={meta['final_acceptance_rate']} median_tta={meta['median_time_to_acceptable_seconds']} ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
