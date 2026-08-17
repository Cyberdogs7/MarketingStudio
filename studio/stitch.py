"""Ad assembly via H3 Retake Stitch (A4 part 2).

Shot 1 renders fresh via ref2va. Every subsequent shot marked ``continuous`` is
rendered as a **retake extension** of the running stitched video
(MiniMaxH3RetakeStitchCS) so the ad becomes one continuous-take MP4 - the same
creator voice is wired into the retake timeline as an audio-timbre segment, so
the voice stays consistent across the whole take. Shots marked
``continuous=false`` (intentional scene change) render fresh via ref2va and are
spliced with an ffmpeg hard-cut concat. Resumable per shot.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from .activity import report
from .adgroup import Ad, AdGroup
from .approval import mark_pending
from .clients.ffmpeg import concat_clips, duration_s
from .compile.durations import snap_duration
from .compile.shot_prompt import compile_stitch_global_prompt
from .config import get_config
from .gpu_manager import ServiceType, get_gpu_manager
from .h3 import build_h3_retake_workflow, run_h3_shot
from .render import (compile_prompt, frame_count, render_client, render_shot,
                     shot_ref_paths, upload_refs)

log = logging.getLogger(__name__)


def _ad_global_prompt(group: AdGroup, ad: Ad) -> str:
    script = ad.read_script()
    style = script.get("style_contract") or {}
    product = group.read_product()
    creator = group.read_creator()
    ad_summary = str(script.get("summary") or "")
    if not ad_summary:
        direction = script.get("direction") or {}
        ad_summary = " ".join(str(s.get("beat") or "") for s in (direction.get("shot_plan") or []))
    return compile_stitch_global_prompt(
        ad_summary=ad_summary, style=style,
        product_description=product.get("canonical_product_description", "") or "",
        creator=creator)


def _voice_segments(client, group: AdGroup, retake_start: int,
                    retake_length: int) -> list[dict]:
    """Wire the creator voice as a timeline audio segment so the retake keeps
    the same vocal timbre (audio refs are timbre, not line reads)."""
    if not group.creator_voice_path.exists():
        return []
    try:
        name = client.upload_audio(group.creator_voice_path)
    except Exception as exc:
        log.warning("voice upload for retake failed: %s", exc)
        return []
    # start=0 + length = window end guarantees the segment overlaps the retake
    # window; load_audio_segment safely clips to the actual sample length.
    return [{"audioFile": name, "trimStart": 0, "start": 0,
             "length": retake_start + retake_length}]


def _render_and_stitch(group: AdGroup, ad: Ad, cfg=None, progress=None) -> Path:
    """Render all shots and assemble the continuous-take final video."""
    cfg = cfg or get_config()
    script = ad.read_script()
    shots = script.get("shots", [])
    if not shots:
        raise RuntimeError("no shots to render")
    client = render_client(cfg)
    fps = int(cfg.get("pipeline", "fps", 24) or 24)
    global_prompt = _ad_global_prompt(group, ad)
    width, height = cfg.get("pipeline", "resolution", [480, 864])
    h3_cfg = cfg.get("comfy", "h3", {})

    running: Path | None = None       # the stitched MP4 so far
    pieces: list[Path] = []           # fresh renders for hard-cut splicing
    done = 0
    with get_gpu_manager(cfg).acquire(ServiceType.COMFYUI):
        for i, shot in enumerate(shots):
            sid = shot.get("id", f"sh{i:02d}")
            duration_s = float(shot.get("duration_s", 10.125))
            _k, frames, _ = snap_duration(duration_s)
            continuous = bool(shot.get("continuous", True)) and running is not None

            if not continuous:
                # Fresh ref2va render of this shot (same voice timbre + product ref).
                raw = ad.video_dir / f"{sid}.mp4"
                if not raw.exists():
                    report(ad.ad_id, f"Rendering {sid} (H3 ref2va)…")
                    render_shot(client, group, ad, shot, seed=i, out_path=raw,
                                cfg=cfg, duration_s=duration_s)
                if running is None:
                    running = raw
                else:
                    pieces.append(raw)

            else:
                # Continuous-take: retake-EXTEND the running stitched video.
                if not group.creator_voice_path.exists():
                    raise RuntimeError(
                        f"cannot stitch {sid} as a continuous take: the creator "
                        f"voice file ({group.creator_voice_path.name}) is missing, "
                        "so the retake would switch to a different voice. Regenerate "
                        "the creator voice in the creator panel, then re-render.")
                stitched = ad.video_dir / f"{sid}_stitched.mp4"
                base_frames = frame_count(running, fps) or 0
                try:
                    base_name = client.upload_video(running)
                except Exception as exc:
                    raise RuntimeError(f"upload base video for retake failed: {exc}")
                report(ad.ad_id, f"Stitching {sid} onto the running take…")
                prompt = compile_prompt(group, ad, shot, len(
                    upload_refs(client, shot_ref_paths(group, ad, sid))))
                audio_segments = _voice_segments(client, group, base_frames, frames)
                wf = build_h3_retake_workflow(
                    prompt, base_name, base_frames, base_frames, frames,
                    global_prompt=global_prompt, seed=i + 1, cfg=cfg,
                    steps=int(h3_cfg.get("steps", 8) or 8),
                    fps=fps, width=int(width), height=int(height),
                    sampler_name=h3_cfg.get("sampler") or "sa_solver",
                    scheduler=h3_cfg.get("scheduler") or "simple",
                    use_spectrum=bool(h3_cfg.get("spectrum", False)),
                    use_first_block_cache=bool(h3_cfg.get("first_block_cache", False)),
                    audio_segments=audio_segments,
                )
                run_h3_shot(client, wf, stitched)
                running = stitched
            done += 1
            if progress:
                progress(done, len(shots), sid)

    # Final assembly: concat any hard-cut pieces in order.
    if pieces:
        final = ad.video_dir / "final.mp4"
        ordered = [ad.video_dir / f"{shots[0]['id']}.mp4"] + pieces
        concat_clips(ordered, final)
        return final
    if running is not None:
        final = ad.video_dir / "final.mp4"
        shutil.copyfile(running, final)
        return final
    raise RuntimeError("no shots were rendered")


def build_video(group: AdGroup, ad: Ad, cfg=None) -> str:
    """Render + stitch the ad. Runs synchronously.

    The dashboard wraps this in a background action (activity.start_action), so
    progress flows through report()/ACTIONS and shows live in the UI. The GPU
    manager acquire is re-entrant, so _render_and_stitch's own acquire nests.
    """
    cfg = cfg or get_config()
    script = ad.read_script()
    total = len(script.get("shots", []))

    def prog(done, n_total, label):
        report(ad.ad_id, f"Rendering {done}/{n_total}: {label}")

    final = _render_and_stitch(group, ad, cfg=cfg, progress=prog)
    dur = duration_s(final)
    mark_pending(ad.dir, "video")
    return f"render complete ({total} shots, {dur:.1f}s)"
