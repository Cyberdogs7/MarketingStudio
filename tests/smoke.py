"""Offline smoke test: full pipeline (product -> creator -> ad script) + dashboard.

Runs with a FAKE LLM (no LM Studio / ComfyUI / H3 needed). Verifies the chunked
script generation chain, the review loop, and the dashboard HTTP layer.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------

class FakeLLM:
    def __init__(self):
        self.calls: list[str] = []

    def chat(self, messages, model=None, temperature=0.7, max_tokens=4096,
             json_mode=False, retries=1, on_progress=None):
        text = _last_text(messages)
        self.calls.append(text[:80])
        if "Revise ONLY the appearance" in text:
            return '{"appearance_canonical": "revised creator"}'
        if "Rewrite this keyframe prompt" in text:
            return "A fixed keyframe prompt, photoreal."
        return "{}"

    def chat_json(self, messages, model=None, temperature=0.4, max_tokens=4096,
                  retries=1, on_progress=None):
        text = _last_text(messages)
        self.calls.append(text[:80])
        if "product normalizer" in text:
            return {
                "category": "skincare", "tier": "premium",
                "usage_mechanic": "press pump", "opening_mechanic": "uncap",
                "key_visuals": "white pump bottle", "label_notes": "small legible label",
                "absent_features": ["cordless"],
                "canonical_product_description": "White 30ml pump bottle, ~12 cm tall, "
                                                 "palm-sized, press pump dispenses onto fingers.",
            }
        if "KNOWN PRESETS" in text:
            return {"name": "Authentic Bathroom GRWM", "register": "NATURAL",
                    "visual_look": "bright bathroom vanity", "lighting": "even soft light",
                    "color_grade": "warm clean", "camera_texture": "steady static",
                    "setting_defaults": ["bathroom"], "wardrobe_anchor": "towel robe",
                    "music_feel": "soft pop bed"}
        if "Direct the ad" in text:
            return {"register": "NATURAL",
                    "persona_sentence": "a warm girl-next-door creator, genuinely delighted.",
                    "hook_pattern": "H4", "story_shape": "S4", "product_entry_shot": 2,
                    "n_shots": 3,
                    "shot_plan": [
                        {"duration_s": 10.125, "beat": "skeptical, opens"},
                        {"duration_s": 10.125, "beat": "product reveal, converts"},
                        {"duration_s": 10.125, "beat": "result + soft CTA"},
                    ]}
        if "SPOKEN LINES ONLY" in text:
            return {"shots": [
                {"id": "sh01", "duration_s": 10.125, "continuous": True,
                 "dialogue": [{"line": "I almost didn't try this.", "on_camera": True}],
                 "summary": "skeptical open"},
                {"id": "sh02", "duration_s": 10.125, "continuous": True,
                 "dialogue": [{"line": "One pump. That's it. Feel that.", "on_camera": True}],
                 "summary": "product reveal"},
                {"id": "sh03", "duration_s": 10.125, "continuous": True,
                 "dialogue": [{"line": "My skin's never looked better.", "on_camera": True}],
                 "summary": "result + CTA"},
            ]}
        if "DIRECTOR OF PHOTOGRAPHY" in text:
            return {"shots": [
                {"id": "sh01", "camera": "selfie, MID, arm's-length, slight handheld"},
                {"id": "sh02", "camera": "static, TIGHT, close-up on product in hand"},
                {"id": "sh03", "camera": "static, MID, eye-level, warm"},
            ]}
        if "ACTION & STAGING DIRECTOR" in text:
            return {"shots": [
                {"id": "sh01", "action": "leans to camera, brow raised",
                 "staging": {"product_visible": "absent", "pov": "selfie", "band": "MID"}},
                {"id": "sh02", "action": "holds pump bottle, presses pump",
                 "staging": {"product_visible": "held", "pov": "static", "band": "TIGHT"}},
                {"id": "sh03", "action": "touches cheek, satisfied nod",
                 "staging": {"product_visible": "held", "pov": "static", "band": "MID"}},
            ]}
        if "SOUND DESIGNER" in text:
            return {"shots": [
                {"id": "sh01", "soundscape": "bathroom echo, low fan", "music": "soft pop bed"},
                {"id": "sh02", "soundscape": "pump click", "music": "soft pop bed"},
                {"id": "sh03", "soundscape": "quiet room", "music": "soft pop bed"},
            ]}
        if "HOOK and COPY craft" in text:
            return {"pass": True, "score": 8, "notes": []}
        if "STORY structure" in text:
            return {"pass": True, "score": 9, "notes": []}
        if "Revise the ad script" in text:
            return {"script": {"shots": json.loads(text.split("CURRENT SCRIPT:")[-1].strip()
                                                   .split("\nReturn ONLY")[0])["shots"]}}
        if "Revise the product contract" in text:
            return {"category": "skincare", "tier": "premium", "usage_mechanic": "press pump",
                    "opening_mechanic": "uncap", "key_visuals": "white pump bottle",
                    "label_notes": "small legible label", "absent_features": ["cordless"],
                    "canonical_product_description": "Revised white 30ml pump bottle."}
        return {}


def _last_text(messages) -> str:
    for msg in reversed(messages or []):
        c = msg.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "text":
                    return part.get("text", "")
    return ""


# ---------------------------------------------------------------------------
# Pipeline smoke
# ---------------------------------------------------------------------------

def _monkeypatch_llm():
    import studio.creator, studio.intake, studio.review, studio.scriptgen, studio.storyboard
    fake = FakeLLM()
    for mod in (studio.intake, studio.creator, studio.scriptgen, studio.review, studio.storyboard):
        mod.llm_client = lambda cfg=None, role="director", timeout=300.0: (fake, "fake-model")
    return fake


def _isolated_config():
    """Config pointed at a throwaway temp root, so the smoke test never
    touches the real ad_groups/. Cleaned up at interpreter exit."""
    import atexit
    import shutil
    import tempfile
    from studio.config import get_config
    cfg = get_config()
    _orig_root = cfg.root
    _tmp = tempfile.TemporaryDirectory()
    cfg.root = Path(_tmp.name)
    atexit.register(lambda: setattr(cfg, "root", _orig_root))
    atexit.register(lambda: _tmp.cleanup())
    # clean slate (temp root only)
    if cfg.ad_groups_dir.exists():
        shutil.rmtree(cfg.ad_groups_dir)
    return cfg


def test_pipeline():
    from studio.adgroup import create_ad_group, list_ad_groups
    from studio.config import get_config
    import studio.intake as intake
    import studio.creator as creator
    import studio.scriptgen as scriptgen
    import studio.review as review

    _monkeypatch_llm()
    cfg = _isolated_config()

    group = create_ad_group("Glow Skincare", "summer glow campaign")
    assert group.group_id == "glow-skincare"

    # 1. product upload + normalize
    from io import BytesIO
    from PIL import Image
    png_buf = BytesIO()
    Image.new("RGB", (1, 1), (200, 180, 170)).save(png_buf, format="PNG")
    png = png_buf.getvalue()
    intake.save_upload(group, "bottle.png", png)
    assert len(intake.list_uploads(group)) == 1
    product = intake.normalize_product(group, cfg=cfg)
    assert product["canonical_product_description"]
    assert product["tier"] in ("luxury", "premium", "drugstore")

    # 2. creator via uploaded photo (no generation needed)
    creator.set_creator_photo(group, intake.list_uploads(group)[0])
    assert group.creator_ref_approved()
    creator.ensure_creator_voice(group, cfg=cfg)
    assert group.creator_voice_path.exists()

    # 3. ad + script
    ad = group.create_ad("Bathroom GRWM", "skeptical to converted", 30, "Authentic Bathroom GRWM")
    script = scriptgen.generate_script(group, ad, cfg=cfg)
    shots = script["shots"]
    assert len(shots) == 3, f"expected 3 shots, got {len(shots)}"
    for s in shots:
        assert s["id"] and s["dialogue"] and s["camera"] and s["action"]
        assert s["staging"]["product_visible"] in ("held", "hidden", "absent")
    assert script["style_contract"]["register"] == "NATURAL"
    assert script["status"] == "pending"
    total = sum(s["duration_s"] for s in shots)
    assert total >= 30 * 0.8, f"runtime too short: {total}"

    # review loop ran (all reviewers passed)
    assert all(r.get("pass") for r in script["reviews"].values())

    # 4. dashboard API
    _test_dashboard()
    print("SMOKE OK: pipeline + dashboard")
    return True


def _test_dashboard():
    import studio.dashboard as dash
    from studio.config import get_config
    cfg = get_config()
    dash.DashboardHandler.cfg = cfg
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", 0), dash.DashboardHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        r = httpx.get(f"{base}/api/state", timeout=10)
        assert r.status_code == 200
        state = r.json()
        assert state["groups"], "expected at least one group"
        g = state["groups"][0]
        assert g["product"]["canonical_product_description"]
        assert len(g["ads"]) == 1
        assert g["ads"][0]["script"]["shots"]

        r = httpx.post(f"{base}/api/action", json={"action": "product.approve", "group": g["id"]})
        assert r.status_code == 200

        r = httpx.get(f"{base}/", timeout=10)
        assert r.status_code == 200 and "Marketing Studio" in r.text
        print(f"dashboard served on :{port}")
    finally:
        server.shutdown()


def test_prompt_dialogue_grammar():
    """The deterministic H3 prompt must declare each shot's vocal state: spoken
    lines inside <d> OR an explicit silence clause - never neither (else H3
    invents gibberish audio). Off-camera lines carry the lips-closed note."""
    from studio.compile.shot_prompt import compile_shot_prompt

    creator = {"name": "Maya", "appearance_canonical": "mid-20s, dark bob"}
    style = {}
    base = dict(shot=None, creator=creator, product_description="",
                style=style, ad_summary="test ad", n_pictures=1, audio_ref=True)

    def build(shot):
        return compile_shot_prompt(**{**base, "shot": shot})

    # 1. on-camera speaking shot + audio ref
    p = build({"id": "sh01", "action": "leans in", "camera": "static MID",
               "dialogue": [{"line": "One pump. That's it.", "on_camera": True}]})
    assert "says, using the voice timbre referenced from <Audio 1>" in p
    assert "<d>[English] One pump. That's it.</d>" in p
    assert "stops speaking after the final line and remains silent" in p

    # 2. off-camera voiceover -> lips-closed note
    p = build({"id": "sh02", "action": "presents the bottle", "camera": "static TIGHT",
               "dialogue": [{"line": "Look at this.", "on_camera": False}]})
    assert "in an off-screen voiceover" in p
    assert "while Maya's lips remain completely closed" in p
    assert "<d>[English] Look at this.</d>" in p

    # 3. SILENT shot -> explicit silence clause, no <d> token
    p = build({"id": "sh03", "action": "holds the bottle, nods", "camera": "static MID",
               "dialogue": []})
    assert "does not speak in this shot" in p
    assert "remains completely silent, lips closed, no dialogue" in p
    assert "<d>" not in p

    # 4. no audio ref -> plain form, closure still present
    p = compile_shot_prompt(**{**base, "audio_ref": False,
                               "shot": {"id": "sh04", "action": "waves", "camera": "selfie MID",
                                        "dialogue": [{"line": "Bye!", "on_camera": True}]}})
    assert "<Subject 1> (S1) says, <d>[English] Bye!</d>" in p
    assert "voice timbre referenced" not in p
    assert "stops speaking after the final line" in p
    print("SMOKE OK: dialogue/silence prompt grammar")
    return True


if __name__ == "__main__":
    test_pipeline()
    test_prompt_dialogue_grammar()
