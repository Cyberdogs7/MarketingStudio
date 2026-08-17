"""Krea 2 (image) ComfyUI access.

``_krea2_render`` returns ``(client, stop)`` where ``client`` talks to the
worker node's ComfyUI and ``stop`` is a no-op cleanup (GPU lifecycle is owned by
the GPU manager).
"""
from __future__ import annotations

from typing import Any

from .clients.comfy import ComfyClient
from .config import get_config


def _krea2_client(cfg=None) -> tuple[ComfyClient, Any]:
    cfg = cfg or get_config()
    node = cfg.get("comfy", "nodes", {}).get("worker", {})
    return ComfyClient(node.get("url", "http://127.0.0.1:8188"),
                       node.get("api_key"), timeout=300), None


def _krea2_render(cfg=None):
    """Return (client, stop) for a Krea 2 render; stop is a no-op."""
    return _krea2_client(cfg)
