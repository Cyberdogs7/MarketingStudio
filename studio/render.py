"""Per-shot H3 rendering (A4 part 1).

Each shot is one MiniMax H3 ref2va generation: upload creator/product refs
(Picture N) + the creator voice (Audio 1), compile the six-section prompt
deterministically, run the workflow, save the MP4. H3 anchors the character's
identity from the creator ref itself, so no keyframes are used. The stitch
orchestrator (stitch.py) then chains the shots into a continuous-take final
video.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .clients.comfy import ComfyClient
from .compile.shot_prompt import compile_shot_prompt
from .config import get_config
from .h3 import build_h3_ref2va_workflow, run_h3_shot

log = logging.getLogger(__name__)


def render_client(cfg=None) -> ComfyClient:
    cfg = cfg or get_config()
    node = cfg.get("comfy", "nodes", {}).get("renderer", {})
    return ComfyClient(node.get("url", "http://127.0.0.1:8188"),
                       node.get("api_key"))


def shot_ref_paths(group, ad, sid: str) -> list[Path]:
    """Reference images for a shot: [creator, product] (existing only)."""
    refs: list[Path] = []
    if group.creator_ref_path.exists():
        refs.append(group.creator_ref_path)
    if group.uploads_dir.exists():
        ups = sorted(p for p in group.uploads_dir.iterdir() if p.suffix.lower() in
                     (".jpg", ".jpeg", ".png", ".webp", ".heic"))
        if ups:
            refs.append(ups[0])
    return refs


def upload_refs(client: ComfyClient, ref_paths: list[Path]) -> list[str]:
    """Upload reference images; returns filenames in the same order (Picture N)."""
    out: list[str] = []
    for p in ref_paths:
        try:
            fname = client.upload_image(p)
            if fname not in out:
                out.append(fname)
        except Exception as exc:
            log.warning("upload ref %s failed: %s", p, exc)
    return out


def compile_prompt(group, ad, shot: dict[str, Any], n_pictures: int) -> str:
    script = ad.read_script()
    style = script.get("style_contract") or {}
    creator = group.read_creator()
    product = group.read_product()
    ad_summary = str(script.get("summary") or shot.get("summary") or "")
    if not ad_summary:
        direction = script.get("direction") or {}
        ad_summary = " ".join(str(s.get("beat") or "") for s in (direction.get("shot_plan") or []))
    return compile_shot_prompt(
        shot=shot,
        creator=creator,
        product_description=product.get("canonical_product_description", "") or "",
        style=style,
        ad_summary=ad_summary,
        n_pictures=n_pictures,
        audio_ref=group.creator_voice_path.exists(),
    )


def render_shot(client: ComfyClient, group, ad, shot: dict[str, Any], seed: int,
                out_path: Path | str, cfg=None, duration_s: float | None = None,
                timeout_s: float = 1800.0) -> Path:
    """Render one H3 ref2va shot (full duration, or override with duration_s)."""
    cfg = cfg or get_config()
    sid = shot.get("id", "shot")
    ref_paths = shot_ref_paths(group, ad, sid)
    image_filenames = upload_refs(client, ref_paths)
    audio_filenames: list[str] = []
    if group.creator_voice_path.exists() and image_filenames:
        try:
            audio_filenames.append(client.upload_audio(group.creator_voice_path))
        except Exception as exc:
            log.warning("voice upload failed: %s", exc)

    prompt = compile_prompt(group, ad, shot, len(image_filenames))
    if duration_s is None:
        duration_s = float(shot.get("duration_s", 10.125))
    h3_cfg = cfg.get("comfy", "h3", {})
    width, height = _canvas(cfg)
    wf = build_h3_ref2va_workflow(
        prompt, duration_s, seed, cfg=cfg,
        ref_image_filenames=image_filenames or None,
        ref_audio_filenames=audio_filenames or None,
        width=width, height=height,
        steps=int(h3_cfg.get("steps", 8) or 8),
        sampler_name=h3_cfg.get("sampler") or "res_multistep",
        scheduler=h3_cfg.get("scheduler") or "simple",
        use_spectrum=bool(h3_cfg.get("spectrum", False)),
        use_first_block_cache=bool(h3_cfg.get("first_block_cache", False)),
    )
    out = Path(out_path)
    try:
        return run_h3_shot(client, wf, out, timeout_s=timeout_s)
    finally:
        try:
            client.free_memory()
        except Exception:
            pass


def render_shot_preview(client: ComfyClient, group, ad, shot: dict[str, Any],
                        seed: int, cfg=None, timeout_s: float = 900.0) -> Path:
    """1-second preview of a shot (same workflow, H3 minimum grid) for cheap QC."""
    from .compile.durations import snap_duration
    cfg = cfg or get_config()
    sid = shot.get("id", "shot")
    out = ad.video_dir / f"{sid}_preview.mp4"
    _k, frames, _ = snap_duration(1.0)
    frames = max(22, frames)
    # Render at minimum grid by clamping the workflow length after build.
    prompt = compile_prompt(group, ad, shot, len(upload_refs(
        client, shot_ref_paths(group, ad, sid))))
    width, height = _canvas(cfg)
    wf = build_h3_ref2va_workflow(prompt, 1.0, seed, cfg=cfg, width=width, height=height,
                                  steps=int(cfg.get("comfy", "h3", {}).get("steps", 8) or 8))
    for _nid, node in wf.items():
        if node.get("class_type") == "MiniMaxH3ReferenceToVideo" and \
           isinstance(node.get("inputs"), dict):
            node["inputs"]["length"] = frames
    try:
        return run_h3_shot(client, wf, out, timeout_s=timeout_s)
    finally:
        try:
            client.free_memory()
        except Exception:
            pass


def _canvas(cfg) -> tuple[int, int]:
    res = cfg.get("pipeline", "resolution", [768, 1344])
    return int(res[0]), int(res[1])


def frame_count(video_path: Path, fps: int = 24) -> int:
    """Best-effort frame count of a video (ffprobe duration * fps)."""
    from .clients.ffmpeg import ffprobe
    info = ffprobe(video_path)
    if not info:
        return 0
    try:
        dur = float(info.get("format", {}).get("duration", 0.0))
        return max(1, int(round(dur * fps)))
    except Exception:
        return 0
