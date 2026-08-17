"""Configuration loader.

Reads ``config/*.yaml`` (one file per top-level section) and deep-merges them
over the built-in defaults below. Unknown keys in YAML are preserved so config
files can carry extra fields without breaking loading.

Sections: pipeline, llm, comfy, approval, reviewers, ugc, env.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

DEFAULTS: dict[str, dict[str, Any]] = {
    "pipeline": {
        "fps": 24,
        "megapixels": 0.4,             # H3 render canvas budget (9:16); ~0.4 MP fits 16 GB VRAM
        "resolution": [512, 896],      # back-compat override; ignored when megapixels is set
        "default_shot_duration_s": 10.125,
        "insert_shot_duration_s": 5.167,
        "max_revisions": 2,
        "max_retakes_per_shot": 2,
        "storyboard_preview_s": 1.0,     # 1s preview length for cheap shot QC
    },
    "llm": {
        "base_url": "http://127.0.0.1:1234/v1",
        "fallback_url": "",
        "concurrency_limit": 4,
        "gpu_guard_urls": [
            "http://127.0.0.1:8188",
            "http://127.0.0.1:8189",
        ],
        "model": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
        "context": 131072,
        "roles": {
            "director": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
            "writer": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
            "shot": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
            "reviewer": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
            "judge": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
            "describer": "",            # vision model (e.g. Qwen2.5-VL) - optional
        },
        "gpu_offload": True,
        "evict_before_render": True,
    },
    "comfy": {
        "nodes": {
            "worker": {"url": "http://127.0.0.1:8188", "api_key": None},
            "renderer": {"url": "http://127.0.0.1:8188", "api_key": None},
        },
        "checkpoints": {
            "krea2": "krea2TurboNSFWAIO_v10.safetensors",
            "krea2_clip": "qwen3vl_4b_fp8_scaled.safetensors",
            "krea2_clip_type": "krea2",
            "krea2_vae": "qwen_image_vae.safetensors",
            "krea2_lora": "fedor_bypass.safetensors",
            "h3_fl2va": "minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
            "h3_ref2va": "minimax_h3_ref2va_pruned_fp8_scaled.safetensors",
            "h3_clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "h3_turbo_lora": "minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors",
            "h3_ref2v_turbo_lora": "minimax_h3_turbo_4step_ckpt500_pruned_comfyui.safetensors",
            "h3_video_vae": "minimax_h3_video_vae_fp16.safetensors",
            "h3_audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
        },
        "manage_lifecycle": True,
        "startup_retries": 30,
        "fp32_vae": True,
        "h3": {
            "spectrum": False,
            "first_block_cache": False,
            "sampler": "res_multistep",
            "scheduler": "simple",
            "steps": 8,
        },
    },
    "approval": {
        "global": {"auto_approve": False},
        "gates": {
            "product": "gated",
            "creator": "gated",
            "voice": "gated",
            "script": "gated",
            "storyboard": "gated",
            "video": "gated",
        },
    },
    "reviewers": {
        "max_revisions": 2,
        "roles": ["hook", "story", "runtime"],
    },
    "ugc": {
        "default_target_s": 30,
        "min_target_s": 15,
        "max_target_s": 60,
        "style_presets": ["Authentic Bathroom GRWM", "Clean Minimal Tech",
                          "Warm Morning Lifestyle", "Gritty Handheld Vlog",
                          "Calm Luxury Aesthetic", "Bright Studio Product"],
        "spoken_ratio_min": 0.70,       # min spoken-runtime fraction for runtime review
        "product_entry_range": [0.40, 0.60],  # when the product enters the story
    },
    "env": {
        "node": "worker",               # worker | renderer
        "portable_root": "portable",
        "lmstudio": {
            "cli": "lms",
            "server_port": 1234,
            "context": 131072,
            "vision_context": 32768,    # smaller KV budget for the vision model
            "gpu_ratio": "max",
            "models": {"director": ""},
        },
        "comfyui": {
            "krea2": {"dir": "", "run": "run_nvidia_gpu.bat", "port": 8188},
            "h3": {"dir": "", "run": "run_nvidia_gpu.bat", "port": 8188},
        },
        "ffmpeg": "",
        "tts": {"venv": "", "sox": "", "models": {"custom_voice": "", "voice_design": ""}},
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into a copy of ``base``."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Config:
    """Loaded, merged configuration. Sections are accessed as attributes."""

    def __init__(self, root: Path | str = ROOT):
        self.root = Path(root)
        self.data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        cfg_dir = self.root / "config"
        merged: dict[str, dict[str, Any]] = copy.deepcopy(DEFAULTS)
        for name in DEFAULTS:
            path = cfg_dir / f"{name}.yaml"
            if path.exists():
                with open(path, "r", encoding="utf-8") as fh:
                    section = yaml.safe_load(fh) or {}
                if isinstance(section, dict):
                    merged[name] = _deep_merge(merged.get(name, {}), section)
        self.data = merged

    def __getitem__(self, section: str) -> dict[str, Any]:
        return self.data[section]

    def get(self, section: str, key: str | None = None, default: Any = None) -> Any:
        sec = self.data.get(section, {})
        if key is None:
            return sec
        return sec.get(key, default)

    @property
    def ad_groups_dir(self) -> Path:
        return self.root / "ad_groups"

    @property
    def workflows_dir(self) -> Path:
        return self.root / "workflows"

    @property
    def rules_dir(self) -> Path:
        return self.root / "studio" / "rules"

    def ad_group_path(self, group_id: str) -> Path:
        return self.ad_groups_dir / group_id

    def list_ad_groups(self) -> list[str]:
        if not self.ad_groups_dir.exists():
            return []
        return sorted(
            p.name for p in self.ad_groups_dir.iterdir()
            if p.is_dir() and (p / "group.json").exists()
        )

    # --- machine / portability ---

    @property
    def node_role(self) -> str:
        return self.get("env", "node", "worker")

    def is_renderer(self) -> bool:
        return self.node_role == "renderer"

    def ffmpeg_bin(self) -> str:
        """Portable ffmpeg path from env.yaml, else the PATH lookup."""
        return self.get("env", "ffmpeg", "") or os.environ.get("STUDIO_FFMPEG", "") or "ffmpeg"

    def lms_cli(self) -> str:
        return self.get("env", "lmstudio", {}).get("cli", "lms") or "lms"

    @property
    def portable_dir(self) -> Path:
        raw = self.get("env", "portable_root", "portable")
        p = Path(raw)
        return p if p.is_absolute() else (self.root / p)

    def comfy_instance(self, which: str) -> dict:
        """Portable ComfyUI instance config ('krea2' or 'h3')."""
        return self.get("env", "comfyui", {}).get(which, {})

    def __repr__(self) -> str:
        return f"Config(root={self.root}, sections={list(self.data)})"


_default: Config | None = None


def get_config(root: Path | str = ROOT) -> Config:
    """Return the process-wide default Config (lazy singleton)."""
    global _default
    if _default is None:
        _default = Config(root)
    return _default
