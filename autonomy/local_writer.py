#!/usr/bin/env python3
"""Zero-key local story writer for TubeAutonomy.

Uses Qwen3 on CPU when GEMINI_API_KEY is not configured. It consumes competitor
content only as research signals and is still followed by the existing semantic
and lexical originality gate before a render job can be packaged.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any


def _json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("local writer did not return a JSON object")
    return json.loads(cleaned[start:end + 1])


def _research(state: dict[str, Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for source in (state.get("sources") or [])[:6]:
        transcript = str(source.get("transcript") or "")
        compact.append({
            "title": source.get("title"),
            "channel": source.get("channelTitle"),
            "viewsPerHour": source.get("viewsPerHour"),
            "trendScore": source.get("trendScore"),
            # Keep local CPU inference prompt compact. These are research excerpts,
            # not material to reproduce.
            "transcriptExcerpt": transcript[:2200],
        })
    return compact


def write_story_local(state: dict[str, Any]) -> dict[str, Any]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_id = os.environ.get("QWEN_WRITER_MODEL", "Qwen/Qwen3-0.6B").strip()
    attempt = int(state.get("attempt", 0)) + 1
    state["attempt"] = attempt
    duration_hint = "45-75 seconds" if state["format"] == "shorts" else "4-8 minutes"

    prompt = f"""
/no_think
You are the Story Writer in an autonomous YouTube production system.
Niche: {state['niche']}
Format: {state['format']} ({duration_hint})

Research signals follow. They are NOT source text to paraphrase. Infer only the
underlying audience interest, then create a genuinely new work with different
wording, examples, sequence, hook and scene design.

RESEARCH:
{json.dumps(_research(state), ensure_ascii=False)}

CHANNEL MEMORY / REWRITE FEEDBACK:
{state.get('originality_feedback') or 'none'}

Return ONLY one valid JSON object. No markdown and no commentary:
{{
  "title": "original title under 90 characters",
  "description": "original YouTube description",
  "tags": ["tag1", "tag2", "tag3"],
  "hook": "opening hook",
  "angle": "the genuinely new angle",
  "script": "complete narration",
  "thumbnailText": "2-5 words",
  "scenes": [
    {{"narration":"scene narration excerpt","visualPrompt":"specific original visual","keywords":["visual","terms"]}}
  ]
}}

Requirements:
- Create new explanatory or storytelling value; never copy distinctive phrases.
- Do not fabricate quotes or claim unknown facts as certain.
- Avoid generic filler and repetitive phrasing.
- Shorts narration should normally be about 100-170 words.
- Scene order must cover the full narration chronologically.
""".strip()

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype="auto",
        low_cpu_mem_usage=True,
    )
    messages = [
        {"role": "system", "content": "Write original, useful YouTube scripts and obey strict JSON output."},
        {"role": "user", "content": prompt},
    ]
    try:
        rendered = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    inputs = tokenizer([rendered], return_tensors="pt")
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=int(os.environ.get("QWEN_WRITER_MAX_NEW_TOKENS", "1300")),
            do_sample=True,
            temperature=0.65,
            top_p=0.9,
            repetition_penalty=1.08,
        )
    new_tokens = generated[0][inputs.input_ids.shape[1]:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True)
    draft = _json_object(text)

    required = ["title", "description", "tags", "script", "thumbnailText", "scenes"]
    missing = [key for key in required if not draft.get(key)]
    if missing:
        raise RuntimeError(f"local Qwen writer output missing fields: {missing}")
    if len(str(draft["script"]).split()) < 45:
        raise RuntimeError("local Qwen writer produced an implausibly short script")
    if not isinstance(draft.get("scenes"), list) or len(draft["scenes"]) < 2:
        raise RuntimeError("local Qwen writer must return at least two scenes")

    state["draft"] = draft
    state["writerEngine"] = model_id
    # Free model memory before the originality model is loaded.
    del model
    del tokenizer
    return state
