"""Ad Group / Ad data model.

An **Ad Group** is the reusable identity container: brand rules, product, creator
identity + voice. Ads are independent full runs under the group - each with its
own direction, duration target, and style contract - all drawing the group's
identity contract verbatim.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .config import get_config


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "group"


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class AdGroup:
    def __init__(self, cfg, group_id: str):
        self.cfg = cfg
        self.group_id = group_id

    # --- paths ---

    @property
    def dir(self) -> Path:
        return self.cfg.ad_group_path(self.group_id)

    @property
    def group_path(self) -> Path:
        return self.dir / "group.json"

    @property
    def brand_path(self) -> Path:
        return self.dir / "brand.json"

    @property
    def product_path(self) -> Path:
        return self.dir / "product.json"

    @property
    def product_approval_path(self) -> Path:
        return self.dir / "product_approval.json"

    @property
    def creator_dir(self) -> Path:
        return self.dir / "creator"

    @property
    def creator_json_path(self) -> Path:
        return self.creator_dir / "creator.json"

    @property
    def creator_ref_path(self) -> Path:
        return self.creator_dir / "ref.png"

    @property
    def creator_refs_json(self) -> Path:
        return self.creator_dir / "refs" / "refs.json"

    @property
    def creator_voice_path(self) -> Path:
        return self.creator_dir / "voice.wav"

    @property
    def uploads_dir(self) -> Path:
        return self.dir / "uploads"

    @property
    def ideas_path(self) -> Path:
        return self.dir / "ideas.json"

    def read_ideas(self) -> dict[str, Any]:
        return _read_json(self.ideas_path, {"ideas": []})

    def write_ideas(self, data: dict[str, Any]) -> None:
        _write_json(self.ideas_path, data)

    # --- group state ---

    def read_group(self) -> dict[str, Any]:
        return _read_json(self.group_path, {"id": self.group_id, "name": self.group_id,
                                            "status": "draft"})

    def write_group(self, data: dict[str, Any]) -> None:
        _write_json(self.group_path, data)

    def read_brand(self) -> dict[str, Any]:
        return _read_json(self.brand_path, {})

    def write_brand(self, data: dict[str, Any]) -> None:
        _write_json(self.brand_path, data)

    def read_product(self) -> dict[str, Any]:
        return _read_json(self.product_path, {})

    def write_product(self, data: dict[str, Any]) -> None:
        _write_json(self.product_path, data)

    def read_product_approval(self) -> dict[str, Any]:
        return _read_json(self.product_approval_path, {"status": "none"})

    def write_product_approval(self, data: dict[str, Any]) -> None:
        _write_json(self.product_approval_path, data)

    # --- creator state ---

    def read_creator(self) -> dict[str, Any]:
        return _read_json(self.creator_json_path, {})

    def write_creator(self, data: dict[str, Any]) -> None:
        _write_json(self.creator_json_path, data)

    def read_creator_refs(self) -> dict[str, Any]:
        return _read_json(self.creator_refs_json, {})

    def write_creator_refs(self, data: dict[str, Any]) -> None:
        _write_json(self.creator_refs_json, data)

    def creator_ref_approved(self) -> bool:
        return (self.read_creator_refs() or {}).get("status") == "real"

    def creator_voice_approved(self) -> bool:
        return self.creator_voice_path.exists()

    # --- ads ---

    @property
    def ads_dir(self) -> Path:
        return self.dir / "ads"

    def list_ads(self) -> list["Ad"]:
        if not self.ads_dir.exists():
            return []
        return [Ad(self, d.name) for d in sorted(self.ads_dir.iterdir())
                if d.is_dir() and (d / "brief.json").exists()]

    def create_ad(self, name: str, direction: str, duration_target_s: int,
                  style: str = "") -> "Ad":
        base = _slug(name) or f"ad{len(self.list_ads()) + 1:02d}"
        ad_id, n = base, 2
        while self.ads_dir.joinpath(ad_id).exists():
            ad_id = f"{base}-{n}"
            n += 1
        ad = Ad(self, ad_id)
        ad.write_brief({
            "name": name or ad_id,
            "id": ad_id,
            "direction": direction,
            "duration_target_s": int(duration_target_s),
            "style": style,               # style preset name, free-form text, or ""
            "status": "draft",
            "style_contract": None,       # filled by the style/direction pass
        })
        return ad

    def find_ad(self, ad_id: str) -> "Ad | None":
        for ad in self.list_ads():
            if ad.ad_id == ad_id:
                return ad
        return None


class Ad:
    def __init__(self, group: AdGroup, ad_id: str):
        self.group = group
        self.ad_id = ad_id

    @property
    def dir(self) -> Path:
        return self.group.ads_dir / self.ad_id

    @property
    def brief_path(self) -> Path:
        return self.dir / "brief.json"

    @property
    def script_path(self) -> Path:
        return self.dir / "script.json"

    @property
    def storyboard_dir(self) -> Path:
        return self.dir / "storyboard"

    @property
    def video_dir(self) -> Path:
        return self.dir / "video"

    @property
    def reviews_dir(self) -> Path:
        return self.dir / "reviews"

    def read_brief(self) -> dict[str, Any]:
        return _read_json(self.brief_path, {"id": self.ad_id, "status": "draft"})

    def write_brief(self, data: dict[str, Any]) -> None:
        _write_json(self.brief_path, data)

    def read_script(self) -> dict[str, Any]:
        return _read_json(self.script_path, {})

    def write_script(self, data: dict[str, Any]) -> None:
        _write_json(self.script_path, data)

    def keyframe_path(self, sid: str) -> Path:
        return self.storyboard_dir / f"{sid}.png"

    def shot_video_path(self, sid: str, stitched: bool = False) -> Path:
        return self.video_dir / f"{sid}{'_stitched' if stitched else ''}.mp4"


def create_ad_group(name: str, brief: str = "") -> AdGroup:
    """Create a new ad group from a name + optional direction. Returns the group."""
    cfg = get_config()
    group_id = _slug(name)
    group = AdGroup(cfg, group_id)
    group.write_group({"id": group_id, "name": name, "brief": brief, "status": "draft"})
    if not group.brand_path.exists():
        group.write_brand({"brand_name": name, "tone_of_voice": "", "approved_claims": [],
                           "banned_claims": [], "audience_notes": ""})
    return group


def list_ad_groups() -> list[AdGroup]:
    cfg = get_config()
    return [AdGroup(cfg, gid) for gid in cfg.list_ad_groups()]


def delete_ad_group(group_id: str) -> bool:
    """Permanently delete an ad group and all its ads, media, and video."""
    cfg = get_config()
    path = cfg.ad_group_path(group_id)
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True
