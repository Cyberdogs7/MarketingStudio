"""ffmpeg/ffprobe helpers (assembly, probing, loudness)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

_FFMPEG: str | None = None
_FFPROBE: str | None = None


def _resolve() -> tuple[str, str]:
    """Resolve portable ffmpeg/ffprobe once (env.yaml path > STUDIO_FFMPEG > PATH)."""
    global _FFMPEG, _FFPROBE
    if _FFMPEG is not None:
        return _FFMPEG, _FFPROBE or "ffprobe"
    base = os.environ.get("STUDIO_FFMPEG", "")
    if not base:
        try:
            from ..config import get_config
            base = get_config().ffmpeg_bin() or ""
        except Exception:
            base = ""
    if base and base != "ffmpeg":
        p = Path(base)
        ffmpeg = str(p)
        ffprobe = str(p.with_name("ffprobe.exe")) if p.suffix.lower() == ".exe" else str(p.with_name("ffprobe"))
        if Path(ffprobe).exists():
            _FFPROBE = ffprobe
        _FFMPEG = ffmpeg
        return _FFMPEG, _FFPROBE or "ffprobe"
    _FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
    _FFPROBE = shutil.which("ffprobe") or "ffprobe"
    return _FFMPEG, _FFPROBE


def _run(args: list[str], probe: bool = False) -> subprocess.CompletedProcess:
    ffmpeg, ffprobe = _resolve()
    bin_path = ffprobe if probe else ffmpeg
    try:
        return subprocess.run([bin_path, *args], capture_output=True, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr="binary not found")


def ffmpeg_version() -> str | None:
    proc = _run(["-version"])
    if proc.returncode != 0:
        return None
    return proc.stdout.splitlines()[0].split(" ")[2] if proc.stdout else "?"


def ffprobe(path: Path | str) -> dict[str, Any] | None:
    """Return the JSON probe dict, or None if ffprobe is unavailable/fails."""
    proc = _run(["-v", "error", "-print_format", "json", "-show_format",
                 "-show_streams", str(path)], probe=True)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def duration_s(path: Path | str) -> float | None:
    info = ffprobe(path)
    if not info:
        return None
    return float(info.get("format", {}).get("duration", 0.0))


def normalize_loudness(path: Path | str, out_path: Path | str,
                       target_lufs: float = -16.0, tp: float = -1.5,
                       lra: float = 11.0) -> Path | None:
    """Two-pass EBU R128 loudness normalization (video copied, audio re-encoded)."""
    path, out_path = Path(path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meas = _run([
        "-i", str(path),
        "-af", f"loudnorm=I={target_lufs}:TP={tp}:LRA={lra}:print_format=json",
        "-f", "null", "-",
    ])
    if meas.returncode != 0:
        return None
    m = re.search(r"\{.*\}", meas.stderr, re.S)
    if not m:
        return None
    try:
        stats = json.loads(m.group(0))
        args = (f"loudnorm=I={target_lufs}:TP={tp}:LRA={lra}:"
                f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
                f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
                f"linear=true")
    except (KeyError, json.JSONDecodeError):
        args = f"loudnorm=I={target_lufs}:TP={tp}:LRA={lra}"
    tmp = out_path.with_suffix(out_path.suffix + ".tmp.mp4")
    proc = _run(["-y", "-i", str(path), "-af", args, "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", str(tmp)])
    if proc.returncode != 0 or not tmp.exists():
        if tmp.exists():
            tmp.unlink()
        return None
    if out_path.exists():
        out_path.unlink()
    tmp.rename(out_path)
    return out_path


def concat_clips(clip_paths: list[Path], out_path: Path) -> None:
    """Hard-cut concat clips with the demuxer (no re-encode of video)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_path.with_suffix(".txt")
    list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in clip_paths), encoding="utf-8")
    proc = _run([
        "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(out_path),
    ])
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {proc.stderr[-500:]}")
