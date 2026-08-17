"""Shared LLM client helper."""
from __future__ import annotations

from typing import Any

from .config import get_config


def llm_client(cfg=None, role: str = "director", timeout: float = 300.0):
    """Return (LMStudioClient, model) for a configured role."""
    from .clients.lmstudio import LMStudioClient
    cfg = cfg or get_config()
    base = cfg.get("llm", "base_url") or "http://127.0.0.1:1234/v1"
    model = cfg.get("llm", "roles", {}).get(role) or cfg.get("llm", "model")
    return LMStudioClient(base, timeout=timeout), model
