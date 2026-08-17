"""Approval gate state machine.

Every gate is a small JSON file under the owning object's dir named
``<gate>.gate.json``: {"status": none|pending|approved|rejected, "notes", "ts"}.
The config decides whether a gate is gated (human) or auto (hands-free); auto
gates flip to approved on generation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import get_config


def gate_file(base: Path, gate: str) -> Path:
    return base / f"{gate}.gate.json"


def read_gate(base: Path, gate: str) -> dict[str, Any]:
    f = gate_file(base, gate)
    if not f.exists():
        return {"gate": gate, "status": "none", "notes": "", "ts": 0}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {"gate": gate, "status": "none", "notes": "", "ts": 0}


def write_gate(base: Path, gate: str, data: dict[str, Any]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    data.setdefault("gate", gate)
    data["ts"] = time.time()
    gate_file(base, gate).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def approve_gate(base: Path, gate: str, notes: str = "") -> dict[str, Any]:
    data = read_gate(base, gate)
    data.update({"status": "approved", "notes": notes})
    write_gate(base, gate, data)
    return data


def reject_gate(base: Path, gate: str, notes: str = "no notes") -> dict[str, Any]:
    data = read_gate(base, gate)
    data.update({"status": "rejected", "notes": notes})
    write_gate(base, gate, data)
    return data


def mark_pending(base: Path, gate: str, notes: str = "") -> dict[str, Any]:
    data = read_gate(base, gate)
    data.update({"status": "pending", "notes": notes})
    write_gate(base, gate, data)
    return data


def gate_approved(base: Path, gate: str) -> bool:
    return read_gate(base, gate).get("status") == "approved"


def gate_mode(cfg=None, gate: str = "") -> str:
    """'gated' or 'auto' for this gate from config/approval.yaml."""
    cfg = cfg or get_config()
    if bool(cfg.get("approval", "global", {}).get("auto_approve", False)):
        return "auto"
    return cfg.get("approval", "gates", {}).get(gate, "gated")


def gate_ready(base: Path, gate: str, cfg=None) -> bool:
    """True when the gate is open (approved, or configured auto)."""
    if gate_mode(cfg, gate) == "auto":
        return True
    return gate_approved(base, gate)


def gate_status_for(base: Path, gate: str) -> str:
    return read_gate(base, gate).get("status", "none")
