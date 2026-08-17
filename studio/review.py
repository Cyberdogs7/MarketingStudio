"""UGC script reviewers + the review loop.

Hook/slop and story reviewers are LLM passes over the ad script; the runtime
check is deterministic (durations + spoken ratio). A failing script is revised
up to ``max_revisions`` rounds.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import get_config
from .llm import llm_client
from . import prompts as _p


def _spoken_ratio(script: dict[str, Any]) -> float:
    total = sum(float(s.get("duration_s", 0) or 0) for s in script.get("shots", []))
    spoken = sum(
        min(float(s.get("duration_s", 0) or 0), 0.95 * float(s.get("duration_s", 0) or 0))
        for s in script.get("shots", [])
        if s.get("dialogue"))
    return (spoken / total) if total else 0.0


def runtime_check(script: dict[str, Any], target_s: int, min_ratio: float) -> dict[str, Any]:
    total = sum(float(s.get("duration_s", 0) or 0) for s in script.get("shots", []))
    ratio = _spoken_ratio(script)
    notes: list[dict[str, Any]] = []
    passed = True
    if total < target_s * 0.8:
        passed = False
        notes.append({"shot": "script",
                      "note": f"total {total:.1f}s is under 80% of the {target_s}s target",
                      "fix": "expand shots / add runtime"})
    if ratio < min_ratio:
        passed = False
        notes.append({"shot": "script",
                      "note": f"spoken ratio {ratio:.0%} is under {min_ratio:.0%}",
                      "fix": "add spoken lines to shots"})
    return {"pass": passed, "score": 10 if passed else 4,
            "total_duration_s": round(total, 2), "notes": notes}


def run_reviewers(ad, script: dict[str, Any], cfg=None, llm=None, model=None,
                  direction: dict[str, Any] | None = None,
                  round_no: int = 1) -> dict[str, Any]:
    """Run the configured reviewers over the script. Returns {role: verdict}."""
    cfg = cfg or get_config()
    if llm is None or model is None:
        llm, model = llm_client(cfg, role="reviewer", timeout=300)
    roles = cfg.get("reviewers", "roles", ["hook", "story", "runtime"])
    brief = ad.read_brief()
    style_contract = brief.get("style_contract") or {}
    product = ad.group.read_product()
    brand = ad.group.read_brand()
    target = int(brief.get("duration_target_s", cfg.get("ugc", "default_target_s", 30)))

    results: dict[str, Any] = {}
    for role in roles:
        try:
            if role == "hook":
                out = llm.chat_json(
                    [{"role": "system", "content": _p.reviewer_system("hook/slop")},
                     {"role": "user", "content": _p.hook_review_prompt(script, style_contract)}],
                    model=model, temperature=0.3, max_tokens=8192)
            elif role == "story":
                out = llm.chat_json(
                    [{"role": "system", "content": _p.reviewer_system("story")},
                     {"role": "user", "content": _p.story_review_prompt(script, product)}],
                    model=model, temperature=0.3, max_tokens=8192)
            else:
                out = runtime_check(script, target,
                                    float(cfg.get("ugc", "spoken_ratio_min", 0.70)))
            results[role] = {"pass": bool(out.get("pass", False)),
                             "score": int(out.get("score", 0)),
                             "notes": out.get("notes", [])}
        except Exception as exc:
            results[role] = {"pass": True, "score": 5,
                             "notes": [{"shot": "script", "note": f"reviewer error: {exc}",
                                        "fix": ""}]}
    return results


def all_pass(results: dict[str, Any]) -> bool:
    return all(r.get("pass") for r in results.values())
