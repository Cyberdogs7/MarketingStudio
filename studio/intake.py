"""Gate 1 - product intake: file upload + LLM normalization -> product.json.

The uploaded photo(s) are read by a vision-capable local LLM (when available) and
normalized ONCE into a canonical contract (category, tier, usage/opening
mechanic, key visuals, absent features, canonical product_description). The
contract is a VERBATIM contract for every downstream stage. Approve/reject lives
in the approval gates.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .adgroup import AdGroup
from .approval import mark_pending
from .config import get_config
from .images import ensure_png
from .llm import llm_client

log = logging.getLogger(__name__)

_ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def save_upload(group: AdGroup, filename: str, data: bytes) -> Path:
    """Persist an uploaded product image under uploads/ and return its path."""
    ext = Path(filename or "product.png").suffix.lower()
    if ext not in _ALLOWED:
        ext = ".png"
    group.uploads_dir.mkdir(parents=True, exist_ok=True)
    out = group.uploads_dir / f"product_{len(list(group.uploads_dir.glob('product_*'))):02d}{ext}"
    out.write_bytes(data)
    ensure_png(out)
    return out


def list_uploads(group: AdGroup) -> list[Path]:
    if not group.uploads_dir.exists():
        return []
    return sorted(p for p in group.uploads_dir.iterdir()
                  if p.suffix.lower() in _ALLOWED)


def _is_digital_feedback(notes: str) -> bool:
    return bool(re.search(
        r"\b(website|web\s*site|web\s*game|browser\s*game|browser|online|mobile\s*app|app|saas|digital|platform)\b",
        notes or "", re.I))


def normalize_product(group: AdGroup, cfg=None, on_progress=None,
                      kind: str | None = None) -> dict[str, Any]:
    """Run the normalization LLM over the uploaded product photo(s).

    ``kind`` (physical|digital) is the human's explicit choice and wins over any
    guess: defaulting to the previously stored kind, else 'physical'. Falls back
    to a minimal contract (no canonical description) when there are no uploads or
    the LLM/vision path fails, so the pipeline never hard-stops here.
    """
    cfg = cfg or get_config()
    current = group.read_product()
    kind = (kind or current.get("product_kind") or "physical")
    llm, model = llm_client(cfg, role="describer", timeout=300)
    brand = group.read_brand()
    images = [str(p) for p in list_uploads(group)]
    msgs = prompts_module().product_normalize_prompt(images, brand, kind)
    try:
        out = llm.chat_json(msgs, model=model, temperature=0.2, max_tokens=8192,
                            on_progress=on_progress)
    except Exception as exc:
        log.warning("product normalization LLM failed for %s: %s", group.group_id, exc)
        out = _fallback_contract(brand)
    if not out.get("canonical_product_description"):
        out["canonical_product_description"] = _fallback_description(brand)
    out["status"] = "pending"
    out.setdefault("category", "")
    out.setdefault("tier", "premium")
    out.setdefault("usage_mechanic", "")
    out.setdefault("opening_mechanic", "")
    out.setdefault("key_visuals", "")
    out.setdefault("label_notes", "")
    out.setdefault("absent_features", [])
    out["product_kind"] = kind
    out.setdefault("source_images", [p.name for p in list_uploads(group)])
    group.write_product(out)
    mark_pending(group.dir, "product")
    return out


def revise_product(group: AdGroup, notes: str, cfg=None) -> dict[str, Any]:
    """Rewrite the product contract from rejection feedback (only flagged fields).

    Feedback that identifies the product as a website / web game / app triggers a
    full digital-product rebuild instead of a patch of the physical description.
    """
    cfg = cfg or get_config()
    current = group.read_product()
    if not current:
        return normalize_product(group, cfg=cfg)
    llm, model = llm_client(cfg, role="director", timeout=300)
    brand = group.read_brand()
    if _is_digital_feedback(notes) or current.get("product_kind") == "digital":
        msgs = prompts_module().product_digital_prompt(current, notes, brand)
        temperature = 0.4
    else:
        msgs = prompts_module().product_revision_prompt(current, notes)
        temperature = 0.3
    try:
        out = llm.chat_json(msgs, model=model, temperature=temperature, max_tokens=8192)
    except Exception as exc:
        log.warning("product revision LLM failed for %s: %s", group.group_id, exc)
        out = dict(current)
    out["status"] = "pending"
    out.setdefault("product_kind", current.get("product_kind") or "physical")
    out.setdefault("source_images", current.get("source_images", []))
    group.write_product(out)
    mark_pending(group.dir, "product", notes)
    return out


def set_product_kind(group: AdGroup, kind: str, cfg=None) -> dict[str, Any]:
    """Force the product contract to 'physical' or 'digital' (human's choice).

    This is the explicit dashboard control the revision-feedback path can only
    reach indirectly. Switching to digital rebuilds the contract as a website /
    web game / app / SaaS (on-screen framing, no physical staging). Switching back
    to physical re-derives the contract from the uploaded photos.
    """
    cfg = cfg or get_config()
    kind = "digital" if kind == "digital" else "physical"
    current = group.read_product()
    if current.get("product_kind") == kind:
        return current
    brand = group.read_brand()
    if kind == "digital":
        notes = ("The advertised product is DIGITAL: a website / web game / app / SaaS, "
                 "not a physical object. Rewrite the whole contract to describe what "
                 "appears ON SCREEN and how the customer engages it digitally.")
        base = current or {"canonical_product_description": "(no contract yet - write it fresh)",
                           "category": "", "tier": "digital"}
        llm, model = llm_client(cfg, role="director", timeout=300)
        try:
            out = llm.chat_json(prompts_module().product_digital_prompt(base, notes, brand),
                                model=model, temperature=0.4, max_tokens=8192)
        except Exception as exc:
            log.warning("digital product rebuild failed for %s: %s", group.group_id, exc)
            out = dict(current) if current else {
                "category": "web game", "tier": "digital", "key_visuals": "",
                "canonical_product_description": f"{brand.get('brand_name') or 'the product'} "
                "is a digital product; details pending manual review."}
    else:
        return normalize_product(group, cfg=cfg, kind="physical")
    out["status"] = "pending"
    out["product_kind"] = "digital"
    out.setdefault("source_images", current.get("source_images", []))
    group.write_product(out)
    mark_pending(group.dir, "product", f"marked as {kind}")
    return out


def _fallback_contract(brand: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": "unknown", "tier": "premium", "usage_mechanic": "",
        "opening_mechanic": "", "key_visuals": "", "label_notes": "",
        "absent_features": [], "canonical_product_description": "",
    }


def _fallback_description(brand: dict[str, Any]) -> str:
    name = brand.get("brand_name") or "the product"
    return (f"A product from {name}. Palm-sized. Details pending manual review - "
            "the uploaded photo was not readable by the local model.")


def prompts_module():
    from . import prompts
    return prompts
