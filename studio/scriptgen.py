"""Per-ad script generation: style -> direction -> monologue -> shot passes -> review.

Mirrors the reference planner's chunked pattern but flat for short-form:
  1. STYLE  - resolve the ad's style contract (once per ad).
  2. DIRECTION - register, persona sentence, hook, story shape, shot plan.
  3. MONOLOGUE - the spoken lines as a shot skeleton (draft).
  4. PASSES - camera -> action -> sound, each merging only its own fields.
  5. REVIEW - hook/story/runtime reviewers; revise up to max_revisions.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import prompts as _p
from .activity import report, report_progress
from .adgroup import Ad, AdGroup
from .approval import mark_pending
from .compile.durations import default_shot_seconds, snap_duration
from .config import get_config
from .llm import llm_client
from .review import all_pass, run_reviewers

REGISTERS = ("NATURAL", "HYPED", "CALM")


def _snap(value: Any, short: bool = False) -> float:
    try:
        return snap_duration(float(value))[2]
    except Exception:
        return default_shot_seconds(short)


def _fit_durations(shots: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    """Scale shot durations to land near the target (each snapped to the H3 grid).

    Uses each shot's pre-snap requested duration (``_req``) so the proportion is
    preserved; iterates until the sum is within tolerance of ``target``.
    """
    if not shots:
        return shots
    req = [float(s.get("_req") or s.get("duration_s", 10.125) or 10.125) for s in shots]
    total = sum(req)
    if total <= 0:
        return shots
    scale = target / total
    snapped: list[float] = []
    for _ in range(4):
        snapped = [snap_duration(r * scale)[2] for r in req]
        t2 = sum(snapped)
        if abs(t2 - target) < 2.0:
            break
        scale *= target / max(t2, 1.0)
    for s, d in zip(shots, snapped):
        s["duration_s"] = d
        s.pop("_req", None)
    return shots


_META_ANNOTATION_RE = __import__("re").compile(r"\*[^*]{1,400}\*")


def _clean_field(text: str) -> str:
    """Strip starred meta-annotations the model sometimes injects ('*Visual Fix: …*')."""
    if not text:
        return text
    return " ".join(_META_ANNOTATION_RE.sub("", text).split())


def _normalize_shots(shots: list[dict[str, Any]], direction: dict[str, Any],
                     target: int, notes: str = "") -> list[dict[str, Any]]:
    """Snap durations, guarantee defaults, tag continuity + product staging."""
    out: list[dict[str, Any]] = []
    for i, s in enumerate(shots or []):
        if not isinstance(s, dict) or not s.get("id"):
            continue
        s = dict(s)
        s["id"] = str(s["id"])
        s.setdefault("duration_s", 10.125)
        s["_req"] = float(s.get("duration_s", 10.125) or 10.125)   # pre-snap for fitting
        s["duration_s"] = _snap(s["_req"])
        s.setdefault("continuous", True)
        s.setdefault("on_camera", True)
        s.setdefault("dialogue", [])
        s.setdefault("camera", "")
        s.setdefault("action", "")
        s.setdefault("staging", {})
        s["staging"].setdefault("product_visible", "absent")
        s["staging"].setdefault("pov", "static")
        s["staging"].setdefault("band", "MID")
        s.setdefault("soundscape", "")
        s.setdefault("music", "")
        s.setdefault("summary", "")
        for k in ("camera", "action", "soundscape", "summary", "music"):
            s[k] = _clean_field(s[k])
        out.append(s)
    return _fit_durations(out, target)


def resolve_style_contract(group: AdGroup, ad: Ad, cfg=None) -> dict[str, Any]:
    """Resolve (once) the ad's style input into a structured style contract."""
    brief = ad.read_brief()
    existing = brief.get("style_contract")
    if isinstance(existing, dict) and existing.get("name"):
        return existing
    cfg = cfg or get_config()
    llm, model = llm_client(cfg, role="director", timeout=300)
    style_input = str(brief.get("style") or "").strip()
    presets = cfg.get("ugc", "style_presets", []) or []
    direction_txt = str(brief.get("direction") or "")
    msgs = [{"role": "user", "content": _p.style_normalize_prompt(style_input, presets, direction_txt)}]
    try:
        out = llm.chat_json(msgs, model=model, temperature=0.4, max_tokens=4096)
    except Exception:
        out = {"name": style_input or "Authentic Bathroom GRWM", "register": "NATURAL",
               "visual_look": "", "lighting": "", "color_grade": "",
               "camera_texture": "", "setting_defaults": [], "wardrobe_anchor": "",
               "music_feel": ""}
    register = str(out.get("register") or "").upper()
    if register not in REGISTERS:
        register = "NATURAL"
    out["register"] = register
    out.setdefault("name", style_input or "Custom Style")
    for k in ("visual_look", "lighting", "color_grade", "camera_texture",
              "setting_defaults", "wardrobe_anchor", "music_feel"):
        out.setdefault(k, "" if k != "setting_defaults" else [])
    brief["style_contract"] = out
    ad.write_brief(brief)
    return out


def generate_script(group: AdGroup, ad: Ad, cfg=None, notes: str = "") -> dict[str, Any]:
    """Run the full per-ad script pipeline. Returns the script dict (status pending)."""
    cfg = cfg or get_config()
    brief = ad.read_brief()
    target = int(brief.get("duration_target_s", cfg.get("ugc", "default_target_s", 30)))
    product = group.read_product()
    creator = group.read_creator()
    brand = group.read_brand()
    style = resolve_style_contract(group, ad, cfg)
    llm, model = llm_client(cfg, role="director", timeout=600)
    system = _p.studio_director_system(brand, style, product)

    # 1. direction
    report(ad.ad_id, "Directing the ad…")
    direction = llm.chat_json(
        [{"role": "system", "content": system},
         {"role": "user", "content": _p.direction_prompt(brief, product, creator, style, target, notes=notes)}],
        model=model, temperature=0.6, max_tokens=16384,
        on_progress=lambda n, t: report_progress(ad.ad_id, "Directing", n, t))
    direction["register"] = style.get("register", "NATURAL")
    try:
        direction["n_shots"] = max(2, min(5, int(direction.get("n_shots", 3))))
    except Exception:
        direction["n_shots"] = 3

    # 2. monologue (draft)
    report(ad.ad_id, "Writing the monologue…")
    monologue = llm.chat_json(
        [{"role": "system", "content": system},
         {"role": "user", "content": _p.monologue_prompt(direction, brief, product, creator, style, brand, notes=notes)}],
        model=model, temperature=0.7, max_tokens=32768,
        on_progress=lambda n, t: report_progress(ad.ad_id, "Monologue", n, t))
    shots = _normalize_shots(monologue.get("shots", []), direction, target, notes)
    if not shots:
        raise RuntimeError("monologue pass returned no shots")

    # 3. shot passes (camera -> action -> sound)
    script = {"status": "pending", "ad_id": ad.ad_id,
              "style_contract": style, "direction": direction, "shots": shots}
    for pass_cfg in _p._SHOT_PASSES:
        report(ad.ad_id, f"Shot pass: {pass_cfg['name']}…")
        out = llm.chat_json(
            [{"role": "system", "content": system},
             {"role": "user", "content": _p.scene_pass_prompt(
                 pass_cfg, script, brief, style, product, creator, brand, direction, target, notes)}],
            model=model, temperature=0.7, max_tokens=32768,
            on_progress=lambda n, t: report_progress(ad.ad_id, pass_cfg["name"], n, t))
        _p._apply_pass(shots, out, pass_cfg)
        script["shots"] = shots

    # 4. review loop
    report(ad.ad_id, "Reviewing the script…")
    max_revisions = int(cfg.get("reviewers", "max_revisions", 2) or 2)
    reviews = run_reviewers(ad, script, cfg=cfg, llm=llm, model=model, direction=direction)
    passed = all_pass(reviews)
    rounds = 1
    while not passed and rounds < max_revisions:
        rounds += 1
        report(ad.ad_id, f"Revising script (round {rounds})…")
        # Keep the revision prompt compact: only the shots (not style/direction/
        # reviews) so the local model doesn't choke on a huge re-echo.
        compact = {"shots": script["shots"]}
        revised = llm.chat_json(
            [{"role": "system", "content": system},
             {"role": "user", "content": _p.revision_prompt(compact, reviews, direction)}],
            model=model, temperature=0.5, max_tokens=65536,
            on_progress=lambda n, t: report_progress(ad.ad_id, "Revision", n, t))
        if isinstance(revised, dict) and isinstance(revised.get("script"), dict):
            revised = revised["script"]
        # Partial revision: merge the returned (changed) shots by id, keeping
        # untouched shots as-is. Keeps the model's output bounded so it never
        # truncates on a full-script rewrite.
        incoming = _normalize_shots((revised or {}).get("shots", []), direction, target, notes)
        if incoming:
            by_id = {s["id"]: s for s in script["shots"]}
            for s in incoming:
                by_id[s["id"]] = s
            script["shots"] = list(by_id.values())
        reviews = run_reviewers(ad, script, cfg=cfg, llm=llm, model=model, direction=direction)
        passed = all_pass(reviews)

    script["reviews"] = reviews
    script["rounds"] = rounds
    script["status"] = "pending"
    ad.write_script(script)
    mark_pending(ad.dir, "script", notes)
    return script


def revise_script(group: AdGroup, ad: Ad, notes: str, cfg=None) -> dict[str, Any]:
    """Re-run generation with rejection feedback threaded as ABSOLUTE notes."""
    cfg = cfg or get_config()
    brief = ad.read_brief()
    # Keep the resolved style contract so a rejection doesn't re-roll the style.
    if brief.get("style_contract"):
        brief["_style_locked"] = True
        ad.write_brief(brief)
    return generate_script(group, ad, cfg=cfg, notes=notes)
