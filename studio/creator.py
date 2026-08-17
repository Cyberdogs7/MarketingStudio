"""Gate 2 - creator: uploaded photo (identity) or generated ref + voice.

An uploaded photo IS the creator (stored verbatim; appearance is never
re-described). Without a photo, the LLM writes a photoreal appearance + voice
spec, Krea 2 renders the base ref, and TTS renders the voice sample. Approve
image and voice separately.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from .adgroup import AdGroup
from .approval import mark_pending
from .clients.tts import TTSService, VoiceConfig
from .clients.tts import is_silent as _is_silent
from .comfy_workflows import generate_keyframe, load_workflow
from .config import get_config
from .gpu_manager import ServiceType, get_gpu_manager
from .images import ensure_png
from .llm import llm_client
from . import prompts as _p

log = logging.getLogger(__name__)


def set_creator_photo(group: AdGroup, photo_path: Path) -> dict[str, Any]:
    """An uploaded photo is the creator identity. Copies it verbatim (as real PNG)."""
    group.creator_dir.mkdir(parents=True, exist_ok=True)
    ensure_png(photo_path)          # uploaded files may be WebP saved as .png
    target = group.creator_ref_path
    target.write_bytes(Path(photo_path).read_bytes())
    ensure_png(target)
    creator = group.read_creator()
    creator["id"] = "creator"
    creator["source"] = "uploaded_photo"
    creator["appearance_canonical"] = ("The person in the uploaded photo, exactly as shown. "
                                       "Never change face, hair, body, or skin tone.")
    creator["persona_sentence"] = creator.get("persona_sentence", "")
    creator["status"] = "pending"
    group.write_creator(creator)
    # Register the refs.json registry entry (status 'real' == a real ref exists).
    group.write_creator_refs({"status": "real", "refs": [target.name],
                              "variants": {"base": target.name}})
    mark_pending(group.creator_dir, "creator")
    return creator


def clear_creator(group: AdGroup) -> None:
    """Remove the creator identity entirely: photo/ref, refs, voice, gates.

    Lets the user start fresh (upload or generate a different creator) without
    stale voice.wav / approval state from the previous identity carrying over.
    """
    d = group.creator_dir
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)



def generate_creator(group: AdGroup, brief: str = "", cfg=None,
                     on_progress=None) -> dict[str, Any]:
    """Creator identity + voice: photo (kept verbatim) or LLM design -> Krea 2 ref.

    An uploaded photo IS the creator: appearance is never re-described; this only
    designs/generates the voice for that identity. Without a photo, the LLM writes
    a photoreal appearance + voice spec, Krea 2 renders the ref, and TTS renders
    the voice sample.
    """
    from .remote_ops import _krea2_render  # local import to keep module graph flat
    cfg = cfg or get_config()
    creator = group.read_creator()
    photo_identity = bool(
        creator.get("source") == "uploaded_photo"
        or (group.creator_dir / "photo_upload.png").exists()
        or group.creator_ref_path.exists()
    )
    style_contract = None
    try:
        style_contract = _first_ad_style(group)
    except Exception:
        pass

    if photo_identity:
        # Keep the uploaded identity; design the voice from the photo with the vision
        # model (describer). Fall back to the canonical appearance text if vision fails.
        creator["source"] = "uploaded_photo"
        creator["appearance_canonical"] = ("The person in the uploaded photo, exactly as shown. "
                                           "Never change face, hair, body, or skin tone.")
        photo = group.creator_dir / "photo_upload.png"
        if not photo.exists():
            photo = group.creator_ref_path
        llm, model = llm_client(cfg, role="describer", timeout=300)
        voice_desc = ""
        for msgs in (_p.creator_voice_from_photo_prompt(str(photo), style_contract, brief),
                     [{"role": "user", "content": _p.creator_voice_prompt(
                         style_contract, brief, creator["appearance_canonical"])}]):
            if voice_desc:
                break
            try:
                out = llm.chat_json(msgs, model=model, temperature=0.6, max_tokens=2048,
                                    on_progress=on_progress)
                voice_desc = (out.get("voice_description") or "").strip()
            except Exception as exc:
                log.warning("voice design (vision) failed for %s: %s", group.group_id, exc)
        creator["voice_description"] = voice_desc or creator.get("voice_description") or ""
        creator["status"] = "pending"
        group.write_creator(creator)
        ensure_creator_voice(group, cfg=cfg)
        mark_pending(group.creator_dir, "creator")
        return group.read_creator()

    llm, model = llm_client(cfg, role="director", timeout=300)
    msgs = [{"role": "user", "content": _p.creator_appearance_prompt(style_contract, brief)}]
    out = llm.chat_json(msgs, model=model, temperature=0.6, max_tokens=4096,
                        on_progress=on_progress)
    creator.update({
        "id": "creator",
        "source": "generated",
        "appearance_canonical": (out.get("appearance_canonical") or "").strip(),
        "voice_description": (out.get("voice_description") or "").strip(),
        "status": "pending",
    })
    group.write_creator(creator)

    # Render the base reference via Krea 2.
    if creator.get("appearance_canonical"):
        refs_dir = group.creator_dir / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        out_png = refs_dir / "creator_ref_01.png"
        if not out_png.exists():
            prompt = (f"Photoreal UGC creator reference portrait. "
                      f"{creator['appearance_canonical']}".rstrip(" .")
                      + ". Front view, neutral standing pose, plain studio background, "
                        "natural light, pore-level skin, high quality. NO anime, no text.")
            wf_path = cfg.workflows_dir / "image_keyframe.json"
            client, stop = _krea2_render(cfg)
            try:
                with get_gpu_manager(cfg).acquire(ServiceType.COMFYUI):
                    generate_keyframe(client, load_workflow(wf_path), prompt, 0, str(out_png),
                                      aspect_ratio="3:4")
                group.write_creator_refs({
                    "status": "real", "refs": [out_png.name],
                    "variants": {"base": out_png.name},
                    "prompt": prompt,
                })
            except Exception as exc:
                log.warning("creator ref render failed for %s: %s", group.group_id, exc)
            finally:
                if stop:
                    stop()

    ensure_creator_voice(group, cfg=cfg)
    mark_pending(group.creator_dir, "creator")
    return group.read_creator()


def revise_creator_ref(group: AdGroup, notes: str, cfg=None) -> bool:
    """Feedback-driven regen of a generated creator's base ref (LLM rewrite)."""
    from .remote_ops import _krea2_render
    cfg = cfg or get_config()
    creator = group.read_creator()
    current = creator.get("appearance_canonical") or ""
    llm, model = llm_client(cfg, role="director", timeout=300)
    try:
        out = llm.chat([{"role": "user", "content":
                         "Revise ONLY the appearance, keep the rest, address the feedback: "
                         f"\nCURRENT:\n{current}\nFEEDBACK:\n{notes}\n"
                         'Reply with ONLY JSON: {"appearance_canonical": "..."}'}],
                       model=model, temperature=0.5, max_tokens=2048)
        import json as _json
        start = out.find("{")
        revised = _json.loads(out[start: out.rfind("}") + 1]).get("appearance_canonical", "").strip()
        if revised:
            creator["appearance_canonical"] = revised
            group.write_creator(creator)
            current = revised
    except Exception as exc:
        log.warning("appearance revision failed for %s: %s", group.group_id, exc)
    if not current:
        return False
    refs_dir = group.creator_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    out_png = refs_dir / "creator_ref_01.png"
    if out_png.exists():
        try:
            out_png.unlink()
        except Exception:
            pass
    prompt = (f"Photoreal UGC creator reference portrait. {current}".rstrip(" .")
              + ". Front view, neutral standing pose, plain studio background, natural light, "
                "pore-level skin, high quality. NO anime, no text.")
    client, stop = _krea2_render(cfg)
    try:
        with get_gpu_manager(cfg).acquire(ServiceType.COMFYUI):
            generate_keyframe(client, load_workflow(cfg.workflows_dir / "image_keyframe.json"),
                              prompt, 0, str(out_png), aspect_ratio="3:4")
        group.write_creator_refs({"status": "real", "refs": [out_png.name],
                                  "variants": {"base": out_png.name}, "prompt": prompt})
        return out_png.exists()
    except Exception as exc:
        log.warning("creator ref regen failed for %s: %s", group.group_id, exc)
        return False
    finally:
        if stop:
            stop()


def ensure_creator_voice(group: AdGroup, cfg=None) -> Path:
    """Synthesize (or no-op) the creator voice sample via the configured TTS."""
    cfg = cfg or get_config()
    creator = group.read_creator()
    out = group.creator_voice_path
    if not out.exists() or _is_silent(out):
        voice = VoiceConfig(
            id="creator",
            mode="designed",
            voice_description=creator.get("voice_description") or "",
        )
        text = (creator.get("persona_sentence") or
                "Hey, can you believe this? I almost didn't try it, but wow.")
        # TTS loads a GPU model in its runner process; serialize with everything else
        # and free VRAM (LLM + ComfyUI) before it runs.
        with get_gpu_manager(cfg).acquire(ServiceType.TTS):
            TTSService(cfg).synthesize(text, voice, out)
    if out.exists():
        mark_pending(group.creator_dir, "voice")
    return out


def _first_ad_style(group: AdGroup) -> dict[str, Any] | None:
    for ad in group.list_ads():
        sc = (ad.read_brief() or {}).get("style_contract")
        if isinstance(sc, dict):
            return sc
    return None
