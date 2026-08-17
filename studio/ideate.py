"""Ad idea brainstorm: LLM concepts from brand + product + creator.

Writes ``ideas.json`` on the group (a list of ad concepts with name/hook/angle/
direction/style/duration). No GPU; the director LLM only. Ideas are proposals -
building an ad from one reuses the normal ``ad.create`` flow.
"""
from __future__ import annotations

import logging
from typing import Any

from .adgroup import AdGroup
from .config import get_config
from .llm import llm_client
from . import prompts as _p

log = logging.getLogger(__name__)


def _creator_image_path(group: AdGroup) -> str:
    """Path of the image shown as the creator identity ('' when none exists)."""
    creator = group.read_creator()
    if creator.get("source") == "generated":
        refs = group.creator_dir / "refs"
        if refs.exists():
            imgs = sorted(refs.glob("*.png"))
            if imgs:
                return str(imgs[-1])
    return str(group.creator_ref_path) if group.creator_ref_path.exists() else ""


def generate_ideas(group: AdGroup, cfg=None, on_progress=None) -> list[dict[str, Any]]:
    """Ask the director for distinct UGC ad concepts and cache them on the group."""
    cfg = cfg or get_config()
    brand = group.read_brand()
    product = group.read_product()
    creator = group.read_creator()
    existing = [ad.read_brief().get("name", "") for ad in group.list_ads()]
    presets = cfg.get("ugc", "style_presets", [])
    llm, model = llm_client(cfg, role="director", timeout=300)
    msgs = _p.ad_ideas_prompt(brand, product, creator, existing, presets,
                              _creator_image_path(group))
    try:
        out = llm.chat_json(msgs, model=model, temperature=0.9, max_tokens=4096,
                            on_progress=on_progress)
    except Exception as exc:
        log.warning("ad ideas LLM failed for %s: %s", group.group_id, exc)
        out = {}
    ideas: list[dict[str, Any]] = []
    for i in (out.get("ideas") or []):
        if not isinstance(i, dict):
            continue
        if not (i.get("name") or i.get("direction")):
            continue
        ideas.append({
            "name": str(i.get("name") or f"Idea {len(ideas) + 1}"),
            "hook": str(i.get("hook") or ""),
            "angle": str(i.get("angle") or ""),
            "direction": str(i.get("direction") or ""),
            "style": str(i.get("style") or ""),
            "duration_target_s": int(i.get("duration_target_s") or 30),
            "why_it_works": str(i.get("why_it_works") or ""),
        })
    group.write_ideas({"status": "pending", "ideas": ideas})
    return ideas
