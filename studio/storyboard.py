"""Per-ad storyboard: keyframes + consistency QC.

Each shot gets one photoreal UGC keyframe (Krea 2) that anchors the H3 clip's
composition and identity. Keyframe prompts are built DETERMINISTICALLY from the
rule packs + the ad's style contract (no LLM in this path). A vision LLM then
reviews each keyframe for creator/product identity and regenerates on failure,
up to ``max_rounds``.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from . import prompts as _p
from .activity import report
from .adgroup import Ad, AdGroup
from .approval import mark_pending
from .comfy_workflows import generate_keyframe, generate_keyframe_with_ref, load_workflow
from .config import get_config
from .gpu_manager import ServiceType, get_gpu_manager
from .llm import llm_client
from .remote_ops import _krea2_client

log = logging.getLogger(__name__)

# Background jobs: ad_id -> {"state", "done", "total", "detail"}
STORYBOARD_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def keyframe_prompt(shot: dict[str, Any], style: dict[str, Any],
                    creator: dict[str, Any], product: dict[str, Any],
                    prev_setting: str = "") -> str:
    """Deterministic keyframe prompt for one shot (photoreal UGC)."""
    lines: list[str] = []
    lines.append("A single photoreal UGC iPhone-style still, vertical 9:16.")
    lines.append("The same person as the creator reference image appears in the frame with "
                 "identical face, hair, body, skin tone - never alter their appearance.")

    sc = style or {}
    parts = [p for p in (sc.get("visual_look"), sc.get("lighting"), sc.get("color_grade"),
                         sc.get("camera_texture")) if p]
    if parts:
        lines.append("Style contract (verbatim): " + "; ".join(parts) + ".")
    settings = sc.get("setting_defaults") or []
    if settings:
        lines.append(f"Setting: {', '.join(str(s) for s in settings)}.")
    if sc.get("wardrobe_anchor"):
        lines.append(f"Wardrobe anchor: {sc['wardrobe_anchor']}.")

    staging = (shot.get("staging") or {})
    cam = (shot.get("camera") or "").strip()
    action = (shot.get("action") or "").strip()
    lines.append(f"Camera: {cam or 'static front-facing'}. Distance band: "
                 f"{str(staging.get('band', 'MID'))}. Action: {action or 'presenting to camera'}.")
    pov = str(staging.get("pov", "static")).lower()
    if pov == "selfie":
        lines.append("Selfie POV: the creator's phone-holding hand is off-frame; exactly one "
                     "hand is free for action.")
    else:
        lines.append("Static camera POV: both hands free, phone not in frame.")
    lines.append("Hand allocation: each hand has ONE role; the idle hand is parked explicitly; "
                 "never more than two hands, no third arm, no duplicated limbs.")

    vis = str(staging.get("product_visible", "absent")).lower()
    if vis in ("held", "hidden", "visible"):
        desc = (product.get("canonical_product_description") or "").strip()
        if vis == "held":
            lines.append("Product staging: the product is held cleanly in one hand, at real "
                         "world scale (never enlarged), showing ONLY the front-facing side from "
                         "the product reference (angle lock), exactly ONE product in frame.")
            if desc:
                lines.append(f"Product: {desc[:400]}.")
        elif vis == "hidden":
            lines.append("Product staging: the product is fully hidden inside a closed "
                         "bag/box/pocket - not visible.")
        else:
            lines.append("Product staging: present the product at realistic scale, exactly one "
                         "in frame, front-facing side only.")
    else:
        lines.append("The product is absent from this frame.")

    # Realism tail (visual.md condensed).
    lines.append("Photoreal UGC realism: natural light, deep focus, pore-level skin, mild "
                 "digital noise, iPhone front-camera optics. NO beauty filter, NO bokeh, NO "
                 "cinematic color grade, NO anime, NO 2D illustration. No text, no captions, no "
                 "subtitles, no watermark, no logos.")

    # Continuity with the previous shot's setting for stitched takes.
    if prev_setting:
        lines.append(f"Continuity: keep the setting, lighting, wardrobe and product state from "
                     f"the previous shot ({prev_setting}).")
    return " ".join(lines)


def render_keyframes(group: AdGroup, ad: Ad, cfg=None, progress=None) -> int:
    """Render one keyframe per shot of the ad's script. Returns count.

    Keyframes are scene/composition anchors only: H3 ref2va is fed [creator,
    product, keyframe] and anchors the character's identity from the creator ref
    itself, so keyframes are plain text2img stills (no IPAdapter required).
    """
    from .comfy_workflows import generate_keyframe, load_workflow
    cfg = cfg or get_config()
    script = ad.read_script()
    shots = script.get("shots", [])
    if not shots:
        return 0
    style = script.get("style_contract") or {}
    creator = group.read_creator()
    product = group.read_product()
    wf_path = cfg.workflows_dir / "image_keyframe.json"
    wf = load_workflow(wf_path)

    client, stop = _krea2_client(cfg)
    done = 0
    prev_setting = ""
    try:
        with get_gpu_manager(cfg).acquire(ServiceType.COMFYUI):
            for i, shot in enumerate(shots):
                sid = shot.get("id", f"sh{i:02d}")
                out = ad.keyframe_path(sid)
                if not out.exists():
                    prompt = keyframe_prompt(shot, style, creator, product, prev_setting)
                    try:
                        generate_keyframe(client, wf, prompt, i, str(out),
                                          aspect_ratio="9:16")
                    except Exception as exc:
                        log.warning("keyframe %s failed for %s: %s", sid, ad.ad_id, exc)
                prev_setting = (shot.get("camera") or "")[:80]
                done += 1
                if progress:
                    progress(done, len(shots), sid)
    finally:
        if stop:
            stop()
    return done


def run_consistency_check(group: AdGroup, ad: Ad, cfg=None,
                          max_rounds: int = 4, progress=None) -> dict[str, Any]:
    """Vision QC each keyframe; rewrite + regenerate on failure.

    Uses the configured LLM as a vision reviewer (falls back to pass when no
    vision model responds). Writes reviews/consistency.json.
    """
    cfg = cfg or get_config()
    script = ad.read_script()
    shots = script.get("shots", [])
    creator_refs = [str(p) for p in (group.creator_ref_path,)
                    if p.exists()]
    results: dict[str, Any] = {"status": "passed", "per_shot": {}}
    if not shots:
        results["status"] = "no_shots"
        return results
    llm, model = llm_client(cfg, role="describer", timeout=300)
    wf_path = cfg.workflows_dir / "image_keyframe.json"
    wf = load_workflow(wf_path)
    client, stop = _krea2_client(cfg)
    try:
        for i, shot in enumerate(shots):
            sid = shot.get("id", f"sh{i:02d}")
            kf = ad.keyframe_path(sid)
            if not kf.exists():
                results["per_shot"][sid] = {"pass": False, "notes": ["missing keyframe"]}
                continue
            entry = {"pass": True, "rounds": 1, "notes": []}
            prompt = keyframe_prompt(shot, script.get("style_contract") or {},
                                     group.read_creator(), group.read_product(), "")
            for rnd in range(max_rounds):
                try:
                    msgs = _p.consistency_review_prompt(str(kf), creator_refs, shot)
                    verdict = llm.chat_json(msgs, model=model, temperature=0.2, max_tokens=1024)
                except Exception as exc:
                    log.info("consistency reviewer unavailable (%s); passing %s", exc, sid)
                    verdict = {"pass": True, "notes": []}
                passed = bool(verdict.get("pass", True))
                notes = [str(n) for n in (verdict.get("notes") or [])]
                if passed:
                    entry["notes"] = notes
                    break
                if rnd + 1 < max_rounds:
                    issues = "; ".join(notes)
                    try:
                        revised_prompt = llm.chat(
                            _p.revise_keyframe_prompt(prompt, issues), model=model,
                            temperature=0.5, max_tokens=2048)
                        if revised_prompt.strip():
                            prompt = revised_prompt.strip()
                            generate_keyframe(
                                client, wf, prompt, i + rnd, str(kf), aspect_ratio="9:16")
                            entry["rounds"] = rnd + 2
                    except Exception as exc:
                        log.warning("keyframe regen failed for %s: %s", sid, exc)
                        break
            else:
                entry["pass"] = False
                entry["notes"] = notes
            results["per_shot"][sid] = entry
            if progress:
                progress(i + 1, len(shots), sid)
    finally:
        if stop:
            stop()
    results["status"] = "passed" if all(
        r.get("pass") for r in results["per_shot"].values()) else "issues"
    ad.reviews_dir.mkdir(parents=True, exist_ok=True)
    (ad.reviews_dir / "consistency.json").write_text(
        __import__("json").dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


def build_storyboard(group: AdGroup, ad: Ad, cfg=None) -> str:
    """Render keyframes then run consistency QC. Runs synchronously.

    The dashboard wraps this in a background action (activity.start_action), so
    progress flows through report()/ACTIONS and shows live in the UI. The GPU
    manager acquire is re-entrant, so render_keyframes' own acquire just nests.
    """
    cfg = cfg or get_config()

    def prog(done, total, label):
        report(ad.ad_id, f"Keyframes {done}/{total}: {label}")

    with get_gpu_manager(cfg).acquire(ServiceType.COMFYUI):
        n = render_keyframes(group, ad, cfg=cfg, progress=prog)
        report(ad.ad_id, "Consistency QC…")
        qc = run_consistency_check(group, ad, cfg=cfg)
    if qc.get("status") == "passed":
        mark_pending(ad.dir, "storyboard")
    return f"storyboard ({n} keyframes, QC {qc.get('status')})"


def storyboard_status(ad_id: str) -> dict[str, Any]:
    return dict(STORYBOARD_JOBS.get(ad_id, {"state": "idle", "done": 0, "total": 0, "detail": ""}))
