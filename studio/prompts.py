"""Prompt builders.

The system ships UGC rule packs under ``studio/rules/``; builders load the packs
and inject them verbatim, so the craft rules live in markdown, not Python. Every
stage demands strict JSON. Only the direction/monologue/shot/review passes call
the LLM; visual prompts (keyframes, H3 prompts) are compiled deterministically.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import get_config

_RULES_DIR = Path(__file__).resolve().parent / "rules"
_rule_cache: dict[str, str] = {}


def load_rule(name: str) -> str:
    """Load a rule pack verbatim (cached)."""
    if name not in _rule_cache:
        p = _RULES_DIR / f"{name}.md"
        _rule_cache[name] = p.read_text(encoding="utf-8") if p.exists() else ""
    return _rule_cache[name]


def reload_rules() -> None:
    _rule_cache.clear()


def _t(d: dict[str, Any], k: str) -> str:
    v = d.get(k, "")
    return str(v).strip() if v else ""


def brand_summary(brand: dict[str, Any]) -> str:
    lines = []
    if _t(brand, "brand_name"):
        lines.append(f"Brand: {brand['brand_name']}")
    if _t(brand, "tone_of_voice"):
        lines.append(f"Tone of voice: {brand['tone_of_voice']}")
    claims = brand.get("approved_claims") or []
    if claims:
        lines.append("APPROVED CLAIMS (use ONLY these exact strings, verbatim): "
                     + "; ".join(str(c) for c in claims))
    banned = brand.get("banned_claims") or []
    if banned:
        lines.append("FORBIDDEN CLAIMS (never make these or anything like them): "
                     + "; ".join(str(c) for c in banned))
    if _t(brand, "audience_notes"):
        lines.append(f"Audience notes: {brand['audience_notes']}")
    return "\n".join(lines) or "(no brand constraints supplied)"


def studio_director_system(brand: dict[str, Any], style_contract: dict[str, Any] | None,
                           product: dict[str, Any] | None = None) -> str:
    """System prompt for the creative director role (all ad script passes)."""
    lines = [
        "You are the creative director of a local UGC marketing studio. You write short-form",
        "ad scripts for TikTok / Instagram: photoreal UGC, a real-feeling creator on camera,",
        "one product, one story, hook-grade copy. Output is ALWAYS strict JSON matching the",
        "requested schema.",
        "",
        "HARD RULES:",
        "- Photoreal UGC only. NEVER anime, never 2D, never stylized illustration.",
        "- The creator is fictional. No minors, no real persons.",
        "- Style and register are decided once per ad and NEVER drift mid-script.",
        f"- Brand constraints (verbatim):\n{brand_summary(brand)}",
    ]
    if style_contract:
        lines.append(f"- Ad style contract (verbatim, never paraphrase):\n"
                     f"{json.dumps(style_contract, ensure_ascii=False, indent=2)}")
    if product:
        lines.append(f"- Product contract (verbatim):\n{_t(product, 'canonical_product_description') or '(no product)'}")
    return "\n".join(lines)


def _image_b64_png(path: Path) -> str:
    """Read an image and return base64-encoded PNG bytes.

    LM Studio accepts only standard data-URI images (png/jpeg); files stored as
    .png may actually be WebP/other, which it rejects. Normalizing to a real PNG
    makes vision work for every uploaded asset.
    """
    import base64
    from io import BytesIO
    from PIL import Image
    with Image.open(str(path)) as im:
        buf = BytesIO()
        im.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()


def _vision_content(image_path: str | None, text: str) -> list[dict] | str:
    """A user message that includes a local image (base64 PNG data URI) when given."""
    if not image_path or not Path(image_path).exists():
        return text
    data = _image_b64_png(Path(image_path))
    return [{"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}]


# ---------------------------------------------------------------------------
# Gate 1 - product intake
# ---------------------------------------------------------------------------

def product_normalize_prompt(image_paths: list[str], brand: dict[str, Any],
                             product_kind: str = "physical") -> list[dict]:
    """Build the user message that reads the uploaded product photo(s).

    ``product_kind`` ('physical' | 'digital') is decided by the human in the
    dashboard and honored as a hard constraint: a digital product's photos are
    screenshots/artwork of a website, web game, app or SaaS, and the contract
    describes what appears ON SCREEN plus the digital interaction.
    """
    digital = product_kind == "digital"
    if digital:
        schema = {
            "product_kind": "'digital'",
            "category": "the real digital category: browser game, web game, mobile app, SaaS, website, tool, ...",
            "tier": "'digital'",
            "usage_mechanic": "how the customer engages it: play in the browser with mouse/touch/keyboard, or use the site/app",
            "opening_mechanic": "how it first starts: open the website, launch, click to start",
            "key_visuals": "what the ad must show ON SCREEN: the game scene / art style / UI / screenshots, not a physical object",
            "label_notes": "visible on-screen text / UI / branding",
            "absent_features": ["features or UI the product does NOT have and must never appear"],
            "canonical_product_description": ("ONE canonical description reused verbatim: what the website/game "
                                              "actually is, what the player does, how it starts, the on-screen "
                                              "look to preserve, absent-feature negatives, one honest imperfection"),
        }
        lead = ("This product is DIGITAL: the attached photo(s) are screenshots / artwork of a website, "
                "web game, app or SaaS - NOT a physical object. Describe what appears ON SCREEN and how "
                "the customer engages it; never stage it like a handheld object.")
    else:
        schema = {
            "product_kind": "'physical'",
            "category": "product category (skincare, fragrance, cosmetics, food, tech, fitness, ...)",
            "tier": "'luxury' | 'premium' | 'drugstore' (read off packaging cues)",
            "usage_mechanic": "exact physical use: spray / squeeze+apply / pump / swipe / brush / drop / scoop / swallow / mix ...",
            "opening_mechanic": "uncap / unscrew / pull tab / flip top / press pump - shown before contents exit",
            "key_visuals": "color, shape, material, label, distinctive features to preserve",
            "label_notes": "what the label looks like and whether text is legible",
            "absent_features": ["features the product does NOT have that must never appear (e.g. cordless, no buttons)"],
            "canonical_product_description": ("ONE canonical staging description reused verbatim: shape, material, color, "
                                              "hand-relative size in cm (never object comparisons), mechanism anatomy, "
                                              "absent-feature negatives, label handling, one honest imperfection"),
        }
        lead = ("Analyze the uploaded product photo(s) and produce the canonical product contract. Read the "
                "physical product carefully: what it exactly is, how it is physically used, how it opens, "
                "its real size relative to a hand.")
    text = (
        "You are the product normalizer for a UGC ad studio. "
        f"{lead}\n"
        f"Brand constraints (verbatim):\n{brand_summary(brand)}\n"
        f"Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\n"
        "No markdown fences."
    )
    if len(image_paths) == 1:
        return [{"role": "user", "content": _vision_content(image_paths[0], text)}]
    msgs = [{"role": "user", "content": text}]
    for p in image_paths:
        msgs.append({"role": "user", "content": _vision_content(p, "This is one of the uploaded product photos.")})
    return msgs


def product_revision_prompt(current: dict[str, Any], notes: str) -> list[dict]:
    schema = {
        "category": ("the product's real category. If the feedback says it is a different kind of "
                     "product (e.g. a browser/web game, an app, a service) then change it to that, "
                     "e.g. 'browser game', 'mobile app', 'SaaS', 'skincare', 'fragrance', 'food'."),
        "tier": "'luxury' | 'premium' | 'drugstore' when it is a physical product, else 'digital'",
        "usage_mechanic": ("the real way the customer engages it: for a game/app the input method "
                           "(mouse/touch/keyboard); for a physical product the physical use."),
        "opening_mechanic": ("how it is first engaged: for a game/app, launch/click to start; for a "
                             "physical product, uncap/unscrew/press/etc."),
        "key_visuals": ("what the ad must show: for a game/app, its art style, UI, and on-screen "
                        "action; for a physical product, the object itself."),
        "label_notes": ("visible text / UI / branding elements shown on screen or on the object, "
                        "or an empty string."),
        "absent_features": ["features/UI the product does NOT have and that must never appear"],
        "canonical_product_description": ("ONE canonical staging description reused verbatim: what "
                                          "the product REALLY is, how it is really engaged, how it "
                                          "first opens/starts, its size or aspect, the visuals to "
                                          "preserve, absent-feature negatives, one honest "
                                          "imperfection."),
    }
    text = (
        "Revise the product contract to honor the director's feedback.\n"
        "RULES:\n"
        "- The FEEDBACK IS AUTHORITATIVE. If it states the product is something other than the "
          "current description (e.g. a browser web game instead of a physical object), then the "
          "product contract MUST be rewritten to describe that corrected product: update category, "
          "usage_mechanic, opening_mechanic, key_visuals and canonical_product_description to "
          "match. 'Made for a web game' is NOT the same as 'is a web game'.\n"
        "- Only fields the feedback does not touch stay unchanged.\n"
        "- Return ONLY valid JSON matching the schema.\n"
        f"CURRENT CONTRACT:\n{json.dumps(current, ensure_ascii=False, indent=2)}\n"
        f"FEEDBACK:\n{notes}\n"
        f"SCHEMA:\n{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return [{"role": "user", "content": text}]


# ---------------------------------------------------------------------------
# Gate 2 - creator
# ---------------------------------------------------------------------------

def creator_appearance_prompt(style_contract: dict[str, Any] | None, brief: str) -> str:
    schema = {
        "appearance_canonical": ("photoreal description of a fictional creator for image "
                                 "generation: age range, hair, build, skin tone, wardrobe anchor. "
                                 "1-3 vivid sentences, un-retouched, no beauty ideal, no real person."),
        "voice_description": "creator voice spec for TTS: gender register, pitch, warmth, age feel.",
    }
    text = (
        "Design the on-camera creator for a UGC ad.\n"
        + (f"Ad style contract:\n{json.dumps(style_contract, ensure_ascii=False, indent=2)}\n"
           if style_contract else "")
        + f"Direction:\n{brief}\n"
          "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return text


def creator_voice_prompt(style_contract: dict[str, Any] | None, brief: str,
                         appearance_canonical: str) -> str:
    """Voice-only design for an identity that already exists (e.g. an uploaded photo)."""
    schema = {
        "voice_description": "creator voice spec for TTS: gender register, pitch, warmth, age feel.",
    }
    text = (
        "Design the voice for the on-camera creator of a UGC ad. The creator's "
        "appearance is FIXED (never change it); design only the voice.\n"
        + (f"Ad style contract:\n{json.dumps(style_contract, ensure_ascii=False, indent=2)}\n"
           if style_contract else "")
        + f"Direction:\n{brief}\n"
        + f"Creator appearance (for voice-appropriateness only):\n{appearance_canonical}\n"
          "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return text


def creator_voice_from_photo_prompt(photo_path: str, style_contract: dict[str, Any] | None,
                                    brief: str) -> list[dict]:
    """Design the voice by actually looking at the uploaded creator photo."""
    schema = {
        "voice_description": ("creator voice spec for TTS derived from the photo: gender register, "
                              "pitch, warmth, energy, age feel, one-line vibe."),
    }
    text = (
        "Look at the uploaded photo of the on-camera creator for a UGC ad. Their appearance "
        "is FIXED (never describe or change it); design ONLY a voice that sounds like the "
        "person in the photo: gender register, pitch, warmth, energy, age feel.\n"
        + (f"Ad style contract:\n{json.dumps(style_contract, ensure_ascii=False, indent=2)}\n"
           if style_contract else "")
        + f"Direction:\n{brief}\n"
          "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return [{"role": "user", "content": _vision_content(photo_path, text)}]


def creator_revise_appearance_prompt(current: str, notes: str) -> list[dict]:
    text = (
        "Revise the creator's canonical appearance to address the director's feedback. Keep "
        "everything the feedback did not ask to change. Return ONLY JSON: "
        '{"appearance_canonical": "..."}'
        f"\nCURRENT:\n{current}\nFEEDBACK:\n{notes}"
    )
    return [{"role": "user", "content": text}]


def product_digital_prompt(current: dict[str, Any], notes: str,
                           brand: dict[str, Any]) -> list[dict]:
    """Rebuild the product contract as a WEBSITE / WEB GAME (not a physical object).

    Used when the director's feedback says the advertised product is digital (a web
    game, website, app, SaaS). The old photo-derived physical description must NOT
    carry over as the product; it is at most in-game artwork.
    """
    schema = {
        "product_kind": "'digital'",
        "category": ("the real category, e.g. 'browser game', 'web game', 'mobile app', "
                     "'SaaS', 'website', 'tool'."),
        "tier": "'digital'",
        "usage_mechanic": ("how the customer actually engages it: e.g. play in the browser with "
                           "mouse/touch/keyboard, or use the site."),
        "opening_mechanic": "how it first starts: e.g. launch, open the website, click to start.",
        "key_visuals": ("what the ad must show ON SCREEN: the game scene / art style / UI / "
                        "screenshots, not a physical object."),
        "label_notes": "visible on-screen text / UI / branding shown.",
        "absent_features": ["features or UI the product does NOT have and must never appear"],
        "canonical_product_description": ("ONE canonical description reused verbatim: what the "
                                          "website/game actually is, what the player does, how it "
                                          "starts, the on-screen look to preserve, absent-feature "
                                          "negatives, one honest imperfection."),
    }
    text = (
        "This product is a WEBSITE / WEB GAME: a digital product, NOT a physical object.\n"
        "RULES:\n"
        "- Rewrite the ENTIRE contract to describe the website/game itself. The physical object "
          "in the source photo is at most an in-game object or artwork - never the product.\n"
        "- key_visuals and canonical_product_description describe what appears ON SCREEN.\n"
        "- usage_mechanic / opening_mechanic are the player's digital interaction.\n"
        "- Return ONLY valid JSON matching the schema.\n"
        f"Brand:\n{brand_summary(brand)}\n"
        f"CURRENT CONTRACT (reference only; correct it fully):\n"
        f"{json.dumps(current, ensure_ascii=False, indent=2)}\n"
        f"DIRECTOR FEEDBACK:\n{notes}\n"
        f"SCHEMA:\n{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return [{"role": "user", "content": text}]


def ad_ideas_prompt(brand: dict[str, Any], product: dict[str, Any],
                    creator: dict[str, Any], existing_ads: list[str],
                    style_presets: list[str], creator_image: str = "") -> list[dict]:
    """Brainstorm distinct short-form UGC ad concepts for the group.

    The creator image (when available) is attached and studied first, so ideas fit
    the creator's actual visual style (photoreal human, 3D animated character, etc.)
    instead of defaulting to real-life influencer setups.
    """
    schema = {
        "ideas": [{
            "name": "short punchy ad title (3-8 words)",
            "hook": "the opening hook line, 1 spoken sentence, hook-grade",
            "angle": "the creative angle in one line",
            "direction": ("how the ad plays out: opening situation, hook beat, mid-story conversion, "
                          "product reveal, close. 2-4 sentences, UGC register, one story."),
            "style": ("a preset from: " + ", ".join(style_presets) +
                      " IF it fits the creator; otherwise a short free-form style "
                      "that fits the creator's look + the product."),
            "duration_target_s": "int 15-60",
            "why_it_works": "one line on why it converts",
        }]
    }
    text = (
        "Brainstorm short-form UGC ad ideas for this product, starring the ATTACHED creator image.\n"
        "STUDY THE CREATOR IMAGE FIRST - they are the on-camera star. Match every idea to the "
        "creator's actual visual style and energy (age, vibe, photoreal vs 3D animated vs cartoon, "
        "etc.). If the creator is 3D/animated/stylized, use game, animation and web-content "
        "appropriate concepts and styles - NEVER default to real-life influencer GRWM / bathroom / "
        "morning-routine setups that would not match them.\n"
        + f"Brand constraints:\n{brand_summary(brand)}\n"
        + f"Product contract (verbatim):\n{_t(product, 'canonical_product_description') or '(no product contract yet)'}\n"
        + f"Creator voice/persona: {_t(creator, 'persona_sentence') or _t(creator, 'voice_description') or '(not set)'}\n"
        + (f"Already produced ads (do NOT repeat these angles or titles): {', '.join(existing_ads)}\n"
           if existing_ads else "")
        + "Return ONLY valid JSON matching this schema (a list of 4-6 ideas):\n"
        + f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return [{"role": "user", "content": _vision_content(creator_image, text)}]


# ---------------------------------------------------------------------------
# Per-ad A1/A2 - style normalization + direction + monologue + shot passes
# ---------------------------------------------------------------------------

def style_normalize_prompt(style_input: str, presets: list[str],
                           brief_direction: str) -> str:
    schema = {
        "name": "style name (a preset name when one matches, else a short descriptive name)",
        "register": "'NATURAL' | 'HYPED' | 'CALM'",
        "visual_look": "one-line framing feel",
        "lighting": "one-line lighting setup",
        "color_grade": "one-line color treatment",
        "camera_texture": "one-line camera feel",
        "setting_defaults": ["likely settings for this style"],
        "wardrobe_anchor": "creator wardrobe for this ad",
        "music_feel": "music bed description or 'none'",
    }
    text = (
        "Resolve the ad's visual style into a single style contract. The contract shape is: "
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\n"
        f"KNOWN PRESETS (when the style input names or clearly matches one, expand its fields "
        f"per your knowledge of it; otherwise treat the input as free-form direction): "
        f"{presets}\n"
        f"STYLE INPUT:\n{style_input or '(none - use a sensible default, e.g. Authentic Bathroom GRWM)'}\n"
        f"AD DIRECTION (keep the contract consistent with it):\n{brief_direction}\n"
        "Return ONLY valid JSON matching the schema. No markdown fences."
    )
    return text


def direction_prompt(brief: dict[str, Any], product: dict[str, Any],
                     creator: dict[str, Any], style_contract: dict[str, Any],
                     target_s: int, notes: str = "") -> str:
    schema = {
        "register": "'NATURAL' | 'HYPED' | 'CALM' (must equal the style contract's register)",
        "persona_sentence": ("ONE sentence defining the creator's performance persona for THIS ad "
                             "(identity + attitude + how they talk). Written once, restated "
                             "verbatim everywhere."),
        "hook_pattern": "'H1'..'H8' from the hook menu",
        "story_shape": "'S1'..'S19' from the story menu",
        "product_entry_shot": "shot index (1-based) where the product first appears - roughly 40-60% of runtime",
        "n_shots": f"integer 2-5 (sum of durations ~ {target_s}s)",
        "shot_plan": [{"duration_s": "per-shot seconds summing to ~target, each snapped near 5.167 or 10.125",
                       "beat": "one sentence: what this shot's beat is and the creator's state"}],
    }
    text = (
        "Direct the ad: pick the register (locked to the style contract), write the persona "
        "sentence, choose the hook pattern and story shape from the menus, and lay out the shot "
        "plan.\n\n"
        f"MONOLOGUE CRAFT RULES (verbatim):\n{load_rule('monologue')}\n\n"
        f"AD BRIEF:\n{json.dumps(brief, ensure_ascii=False, indent=2)}\n"
        f"STYLE CONTRACT:\n{json.dumps(style_contract, ensure_ascii=False, indent=2)}\n"
        f"PRODUCT:\n{_t(product, 'canonical_product_description')}\n"
        f"CREATOR PERSONA/APPEARANCE:\n{json.dumps(creator, ensure_ascii=False, indent=2)}\n"
        f"DURATION TARGET: {target_s}s\n"
        "The product enters the story at ~40-60% of runtime as a supporting actor; the CTA rides "
        "inside the closer's resolution, never an outro beat.\n"
        + (f"\nABSOLUTE DIRECTOR CONSTRAINTS (from the last rejection - every one is mandatory, "
           f"and they OVERRIDE the brief/brand/product where they conflict):\n{notes}\n" if notes else "")
        + "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return text


def monologue_prompt(direction: dict[str, Any], brief: dict[str, Any],
                     product: dict[str, Any], creator: dict[str, Any],
                     style_contract: dict[str, Any], brand: dict[str, Any],
                     notes: str = "") -> str:
    schema = {
        "shots": [{
            "id": "sh01, sh02, ...",
            "duration_s": "float from the shot plan",
            "continuous": "bool - true when this shot continues the previous take in the same place (H3 stitch), false on an intentional scene change",
            "dialogue": [{"line": "spoken line", "on_camera": "bool"}],
            "summary": "one sentence: what happens in this shot",
        }],
    }
    text = (
        "Write the ad's monologue as a list of shots. You are writing SPOKEN LINES ONLY - "
        "camera, action, staging and sound are filled by later passes. Apply the monologue "
        "craft rules to every line.\n\n"
        f"MONOLOGUE CRAFT RULES (verbatim):\n{load_rule('monologue')}\n\n"
        f"DIRECTION (register, persona sentence, hook, story shape, shot plan - follow it):\n"
        f"{json.dumps(direction, ensure_ascii=False, indent=2)}\n"
        f"AD BRIEF:\n{json.dumps(brief, ensure_ascii=False, indent=2)}\n"
        f"STYLE CONTRACT:\n{json.dumps(style_contract, ensure_ascii=False, indent=2)}\n"
        f"PRODUCT:\n{_t(product, 'canonical_product_description')}\n"
        f"BRAND:\n{brand_summary(brand)}\n"
        f"CREATOR:\n{_t(creator, 'persona_sentence')}\n"
        "Rules:\n"
        "- The creator SPEAKS AS the persona in persona_sentence; the persona_sentence itself "
          "NEVER appears in any line.\n"
        "- dialogue['line'] contains ONLY the exact words spoken aloud - a clean, spoken "
          "sentence. No descriptions, no persona/voice text, no stage directions, no narrator "
          "prose.\n"
        "- Word budget per shot from the density table; ~70% of runtime should be spoken.\n"
        "- The register, hook and story shape are VERBATIM contracts - do not vary them.\n"
        + (f"\nABSOLUTE DIRECTOR CONSTRAINTS (from the last rejection - follow every one; they "
           f"OVERRIDE the brand/direction/product where they conflict):\n{notes}\n" if notes else "")
        + "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return text


# UGC shot passes: monologue (draft) -> camera -> action -> sound. Later passes
# merge ONLY their own fields into the draft, keyed by shot id.
_SHOT_PASSES: list[dict[str, Any]] = [
    {
        "name": "camera",
        "job": "DIRECTOR OF PHOTOGRAPHY (photoreal UGC)",
        "schema": {"shots": [{
            "id": "shot id (verbatim)",
            "camera": "framing, angle, lens feel, movement, POV (selfie or static) and distance band (TIGHT/MID/WIDE)",
        }]},
        "instructions": (
            "Describe each shot's camera. Enforce the ANTI-MORPH rule: no two adjacent shots "
            "share BOTH their POV and their distance band. Match the shot's beat and the ad's "
            "camera_texture."),
        "fields": ["camera"],
    },
    {
        "name": "action",
        "job": "ACTION & STAGING DIRECTOR",
        "schema": {"shots": [{
            "id": "shot id (verbatim)",
            "action": "what the creator physically does, one continuous movement, hands named",
            "staging": {"product_visible": "'held' | 'hidden' | 'absent'",
                        "pov": "'selfie' | 'static'",
                        "band": "'TIGHT' | 'MID' | 'WIDE'"},
        }]},
        "instructions": (
            "Describe each shot's physical action with the hand allocation rule (2 hands, one "
            "role each, idle hand parked) and the safe interaction verbs. Set product_visible "
            "per the shot: product appears only where the beat needs it. Follow the mechanism "
            "anatomy and one-state-per-prop rules."),
        "fields": ["action", "staging"],
    },
    {
        "name": "sound",
        "job": "SOUND DESIGNER",
        "schema": {"shots": [{
            "id": "shot id (verbatim)",
            "soundscape": "background / environment sound",
            "music": "music cue or 'none'",
        }]},
        "instructions": (
            "Give each shot its background soundscape and music cue matching the beat and the "
            "style's music_feel. Use 'none' for silent beats."),
        "fields": ["soundscape", "music"],
    },
]


def _apply_pass(draft: list[dict[str, Any]], out: dict[str, Any],
                pass_cfg: dict[str, Any]) -> None:
    """Merge ONE pass's output into the draft, keyed by shot id."""
    by_id = {s.get("id"): s for s in draft}
    for item in (out.get("shots") or []):
        if not isinstance(item, dict):
            continue
        shot = by_id.get(item.get("id"))
        if shot is None:
            continue
        for f in pass_cfg.get("fields", []):
            if f in item and item[f] is not None:
                shot[f] = item[f]
        for top, keys in pass_cfg.get("nested", []):
            nsrc = item.get(top)
            if not isinstance(nsrc, dict):
                continue
            ndst = shot.setdefault(top, {})
            for k in keys:
                if k in nsrc and nsrc[k] is not None:
                    ndst[k] = nsrc[k]


def scene_pass_prompt(pass_cfg: dict[str, Any], script: dict[str, Any],
                      brief: dict[str, Any], style_contract: dict[str, Any],
                      product: dict[str, Any], creator: dict[str, Any],
                      brand: dict[str, Any], direction: dict[str, Any],
                      target_s: int, notes: str = "") -> str:
    """Build ONE focused 'job description' prompt for a single shot pass."""
    job = pass_cfg["job"]
    schema = pass_cfg["schema"]
    instructions = pass_cfg.get("instructions", "")
    draft = script.get("shots") or []
    context = ("CURRENT AD SHOT DRAFT - every field already written by an earlier pass is FINAL; "
               "preserve it exactly. Write ONLY your own field(s) and return the FULL shot list.\n"
               + json.dumps(draft, indent=2, ensure_ascii=False)) if draft else (
        "There is no draft yet (this pass is the first). Return the full shot list for your field(s).")
    if notes.strip():
        context += ("\n\nDIRECTOR'S FEEDBACK ON THE CURRENT SHOTS (ABSOLUTE - apply every "
                    f"point in this pass):\n{notes}")
    rules = "\n\n".join(p for p in (
        load_rule("performance"), load_rule("product"), load_rule("visual")) if p)
    text = (
        f"You are the {job} for ONE UGC ad. Each shot is one H3 video clip.\n\n"
        f"Your output schema (return ONLY this shape):\n{json.dumps(schema, indent=2, ensure_ascii=False)}\n\n"
        f"PERFORMANCE / PRODUCT / VISUAL RULES (verbatim):\n{rules}\n\n"
        f"AD BRIEF:\n{json.dumps(brief, ensure_ascii=False, indent=2)}\n"
        f"STYLE CONTRACT:\n{json.dumps(style_contract, ensure_ascii=False, indent=2)}\n"
        f"PRODUCT:\n{_t(product, 'canonical_product_description')}\n"
        f"DIRECTION:\n{json.dumps(direction, ensure_ascii=False, indent=2)}\n\n"
        f"{context}\n\n"
        f"YOUR JOB:\n{instructions}\n"
        f"DURATION TARGET: {target_s}s\n"
        "- Keep every shot id exactly as given; never add, remove, or reorder shots.\n"
        "- Photoreal UGC only; never anime; no real persons; no minors.\n"
        "- Return ONLY valid JSON matching the schema. No markdown fences, no commentary."
    )
    return text


# ---------------------------------------------------------------------------
# Review loop
# ---------------------------------------------------------------------------

def reviewer_system(role: str) -> str:
    return (
        f"You are the {role} reviewer for a UGC ad studio. You read an ad script (shots with "
        "dialogue, camera, action, staging) and return strict JSON verdicts. You are strict and "
        "specific: every failing note names the shot and the exact problem. Photoreal UGC, never "
        "anime. No real persons, no minors."
    )


def hook_review_prompt(script: dict[str, Any], style_contract: dict[str, Any]) -> str:
    schema = {
        "pass": "bool",
        "score": "0-10",
        "notes": [{"shot": "shot id or 'script'", "note": "specific problem", "fix": "what to change"}],
    }
    text = (
        "Review the ad script's HOOK and COPY craft against these rules (verbatim):\n"
        f"{load_rule('monologue')}\n\n"
        "Check: banned openers/words, first-word constraint, one peak per shot, every claim "
        "carries a concrete (or is an approved brand claim), hook pattern + story shape are "
        "respected, CTA rides inside the closer (no outro beat).\n"
        f"STYLE CONTRACT:\n{json.dumps(style_contract, ensure_ascii=False, indent=2)}\n"
        f"SCRIPT:\n{json.dumps(script, ensure_ascii=False, indent=2)}\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return text


def story_review_prompt(script: dict[str, Any], product: dict[str, Any]) -> str:
    schema = {
        "pass": "bool",
        "score": "0-10",
        "notes": [{"shot": "shot id or 'script'", "note": "specific problem", "fix": "what to change"}],
    }
    text = (
        "Review the ad's STORY structure: exactly one 'but then' twist, human stakes first, the "
        "product enters as a supporting actor at ~40-60% of runtime, the closer resolves inside "
        "its final shot, the story survives with the product deleted.\n"
        f"PRODUCT:\n{_t(product, 'canonical_product_description')}\n"
        f"SCRIPT:\n{json.dumps(script, ensure_ascii=False, indent=2)}\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return text


def runtime_review_prompt(script: dict[str, Any], target_s: int) -> str:
    schema = {
        "pass": "bool",
        "score": "0-10",
        "total_duration_s": "float",
        "notes": [{"shot": "shot id or 'script'", "note": "specific problem", "fix": "what to change"}],
    }
    text = (
        "Review the ad's RUNTIME/format: shot durations snapped to ~5.167s or ~10.125s, total "
        f"near the {target_s}s target (>= 80%), and at least ~70% of runtime is spoken dialogue. "
        f"Script:\n{json.dumps(script, ensure_ascii=False, indent=2)}\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return [{"role": "user", "content": text}]


def revision_prompt(script: dict[str, Any], reviews: dict[str, Any], direction: dict[str, Any]) -> str:
    schema = {
        "shots": [{
            "id": "shot id - ONLY shots that must change",
            "duration_s": "float", "continuous": "bool",
            "dialogue": [{"line": "str", "on_camera": "bool"}],
            "camera": "str", "action": "str",
            "staging": {"product_visible": "str", "pov": "str", "band": "str"},
            "soundscape": "str", "music": "str", "summary": "str",
        }],
    }
    text = (
        "Revise the ad script addressing EVERY reviewer note. Return ONLY the shots that must "
        "change, each FULLY populated (every field). Shots you do not return are kept exactly "
        "as-is. Keep the total duration near target. The direction (register, persona sentence, "
        "hook, story shape) is a VERBATIM contract - do not change it.\n"
        f"DIRECTION (VERBATIM, do not change):\n{json.dumps(direction, ensure_ascii=False, indent=2)}\n"
        f"REVIEWS:\n{json.dumps(reviews, ensure_ascii=False, indent=2)}\n"
        f"CURRENT SCRIPT (return only the changed shots):\n{json.dumps(script, ensure_ascii=False, indent=2)}\n"
        "Return ONLY valid JSON matching this schema (a partial shot list):\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\nNo markdown fences."
    )
    return text


# ---------------------------------------------------------------------------
# Storyboard + consistency QC (vision LLM)
# ---------------------------------------------------------------------------

def consistency_review_prompt(keyframe_path: str, ref_paths: list[str],
                              shot: dict[str, Any]) -> list[dict]:
    schema = {
        "pass": "bool",
        "notes": ["specific visual defects found"],
    }
    text = (
        "Vision QC for one keyframe. Check RENDERING SANITY only - the character's identity is "
        "NOT decided here (the video model anchors identity from its own reference image), and "
        "the keyframe need not match a reference person. Verify: hand count <= 2 with no "
        "extra/duplicated limbs; the product appears per the shot's staging (held/visible/"
        "absent) with at most ONE hero product at sane scale; no gibberish, reversed or foreign "
        "labels; no baked text, captions, subtitles, watermarks or logos; composition matches "
        "the shot's camera and action description.\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\n"
        f"SHOT:\n{json.dumps(shot, ensure_ascii=False, indent=2)}"
    )
    msgs = [{"role": "user", "content": text}]
    for p in ([keyframe_path] + ref_paths):
        msgs.append({"role": "user", "content": _vision_content(p, "Reference/review image.")})
    return msgs


def revise_keyframe_prompt(current_prompt: str, issues: str) -> list[dict]:
    text = (
        "Rewrite this keyframe prompt to fix the vision-QC issues. Keep everything that was "
        "correct; change only what the issues demand. Photoreal UGC, no anime, no text.\n"
        f"CURRENT PROMPT:\n{current_prompt}\n"
        f"ISSUES:\n{issues}\n"
        "Reply with ONLY the rewritten prompt text."
    )
    return [{"role": "user", "content": text}]
