"""TTS adapter interface + engines.

v0 ships a NullTTS adapter (valid silent WAV) so the pipeline runs before TTS is
wired, plus a shell-out adapter for the user's proven Qwen3-TTS stack when a
runner script + venv are configured in env.yaml (``env.tts.venv`` and
``env.tts.runner``). Any synthesis failure degrades to a silent sample so the
creator/approval chain never blocks on the audio stack.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import get_config

logger = logging.getLogger(__name__)


@dataclass
class VoiceConfig:
    """A creator voice: preset or designed (free-text) description."""

    id: str
    engine: str = "qwen3_tts"
    mode: str = "designed"          # preset | designed
    speaker: str | None = None      # preset: named speaker pool entry
    voice_description: str = ""     # designed: free-text voice spec
    speed: float = 1.0
    pitch: float = 0.0

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            f"{self.speaker}|{self.voice_description}".encode()
        ).hexdigest()


class TTSAdapter(Protocol):
    def synthesize(self, text: str, voice: VoiceConfig, out_path: Path) -> float:
        """Render text -> wav at out_path; return duration in seconds."""


class Qwen3TTSAdapter:
    """Shell out to a Qwen3-TTS runner script (``studio/tts_runner.py`` by default).

    The runner is expected to accept: ``--text``, ``--out``, and either
    ``--voice-description`` (designed) or ``--speaker`` (preset), plus optional
    ``--model`` and ``--sox-dir``. Runs with the venv configured in env.yaml.
    """

    def __init__(self, runner: str = "", python: str = "", config=None):
        self.runner = runner
        self.python = python
        self.config = config

    def health(self) -> bool:
        cfg = self.config or get_config()
        return bool(cfg.get("env", "tts", {}).get("venv", ""))

    def synthesize(self, text: str, voice: VoiceConfig, out_path: Path) -> float:
        cfg = self.config or get_config()
        env_tts = cfg.get("env", "tts", {}) or {}
        python = self.python or env_tts.get("venv", "") or ""
        runner = self.runner or (env_tts.get("runner") or "") or ""
        if runner:
            rp = Path(runner)
            if not rp.is_absolute():
                rp = Path(__file__).resolve().parent.parent / rp
        else:
            rp = Path(__file__).resolve().parent.parent / "tts_runner.py"
        if not python:
            logger.info("no tts venv configured; writing silent sample for %s", voice.id)
            return NullTTS().synthesize(text, voice, out_path)
        if not rp.exists():
            logger.warning("tts runner not found (%s); writing silent sample for %s", rp, voice.id)
            return NullTTS().synthesize(text, voice, out_path)
        model = (env_tts.get("models", {}) or {}).get(
            "voice_design" if voice.mode == "designed" else "custom_voice", "")
        sox = env_tts.get("sox", "")
        cmd = [python, str(rp), "--text", text, "--out", str(out_path)]
        if voice.mode == "designed":
            cmd += ["--voice-description", voice.voice_description or ""]
        else:
            cmd += ["--speaker", voice.speaker or ""]
        if model:
            cmd += ["--model", model]
        if sox:
            cmd += ["--sox-dir", sox]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=900)
        except Exception as exc:
            logger.warning("Qwen3-TTS synthesis failed (%s); writing silent sample", exc)
            return NullTTS().synthesize(text, voice, out_path)
        return _duration(out_path)


class NullTTS:
    """Placeholder engine: writes a valid silent WAV in pure Python (no ffmpeg)."""

    def health(self) -> bool:
        return True

    def synthesize(self, text: str, voice: VoiceConfig, out_path: Path) -> float:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 24000
        duration = max(0.5, min(5.0, 0.25 + len(text) * 0.06))
        _write_silent_wav(out_path, sample_rate, duration)
        return duration


def is_silent(path: Path) -> bool:
    """True when the wav is empty or has no non-zero sample in the first ~1s."""
    try:
        import array
        import wave
        with wave.open(str(path), "rb") as w:
            n = w.getnframes()
            if n == 0:
                return True
            data = w.readframes(min(n, 24000))
            samples = array.array("h", data)
            return max((abs(s) for s in samples), default=0) == 0
    except Exception:
        return True


def _write_silent_wav(path: Path, sample_rate: int, duration: float) -> None:
    """Write a minimal valid 16-bit mono PCM WAV of silence."""
    import struct

    n_samples = int(sample_rate * duration)
    data = b"\x00\x00" * n_samples
    byte_rate = sample_rate * 2
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" \
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, 2, 16) \
        + b"data" + struct.pack("<I", len(data))
    path.write_bytes(header + data)


class TTSService:
    """Registry: engine id -> adapter."""

    def __init__(self, config=None):
        self.config = config or get_config()
        self._adapters = {
            "qwen3_tts": Qwen3TTSAdapter(config=self.config),
            "null": NullTTS(),
        }

    def register(self, engine: str, adapter: TTSAdapter) -> None:
        self._adapters[engine] = adapter

    def get(self, engine: str) -> TTSAdapter:
        return self._adapters.get(engine, self._adapters["null"])

    def synthesize(self, text: str, voice: VoiceConfig, out_path: Path) -> float:
        """Pick the adapter by voice.engine, cache by fingerprint (idempotent).

        Silent/empty cached samples are never reused and never written back to the
        cache, so a failed synthesis can't poison future runs.
        """
        cache_dir = self.config.root / "cache" / "tts"
        cache_path = cache_dir / f"{voice.fingerprint}-{hashlib.sha256(text.encode()).hexdigest()[:12]}.wav"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists() and not is_silent(cache_path):
            out_path.write_bytes(cache_path.read_bytes())
            return _duration(cache_path)
        duration = self.get(voice.engine).synthesize(text, voice, out_path)
        if out_path.exists() and not is_silent(out_path):
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(out_path.read_bytes())
        return duration


def _duration(path: Path) -> float:
    from .ffmpeg import ffprobe
    info = ffprobe(path)
    return float(info.get("format", {}).get("duration", 0.0)) if info else 0.0
