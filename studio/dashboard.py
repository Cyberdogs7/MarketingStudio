"""Dashboard HTTP server - all Marketing Studio UX.

Serves the single-page dashboard and a small JSON API. Every gate, upload,
approve/reject, and pipeline action is driven from here. Background pipeline
actions run in threads and report through activity.ACTIONS / ACTIVITY.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import activity
from . import approval as _appr
from . import creator as _creator
from . import ideate as _ideate
from . import intake as _intake
from . import scriptgen as _scriptgen
from . import stitch as _stitch
from .activity import ACTIONS, ACTIVITY, report, start_action
from .adgroup import AdGroup, create_ad_group, delete_ad_group, list_ad_groups
from .approval import (approve_gate, gate_mode, gate_status_for, mark_pending,
                       read_gate, reject_gate)
from .config import get_config

log = logging.getLogger(__name__)

_HTML = Path(__file__).resolve().parent / "dashboard.html"


class _EventBus:
    """SSE fan-out: every client gets a queue; notify() wakes them all."""

    def __init__(self):
        self._queues: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def notify(self) -> None:
        with self._lock:
            queues = list(self._queues)
        if not queues:
            return
        payload = "event: state\ndata: refresh\n\n"
        for q in queues:
            try:
                q.put_nowait(payload)
            except Exception:
                pass


_bus = _EventBus()
activity.subscribe(_bus.notify)


def _json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def _group_of(cfg, gid) -> AdGroup:
    return AdGroup(cfg, gid)


def _ad_of(group: AdGroup, aid: str):
    return group.find_ad(aid)


def _gate_state(base_path, gate: str, cfg) -> dict:
    r = read_gate(base_path, gate)
    return {"gate": gate, "status": r.get("status", "none"), "notes": r.get("notes", ""),
            "mode": gate_mode(cfg, gate)}


def _shot_videos(ad, script) -> list[dict]:
    """Per-shot clip for each scripted shot: the continuous-take stitched mp4
    when present (that shot's segment of the running take), else the fresh
    ref2va render of the shot."""
    out: list[dict] = []
    for s in script.get("shots") or []:
        sid = s.get("id", "")
        if not sid:
            continue
        for name, kind in ((f"{sid}_stitched.mp4", "stitched"),
                           (f"{sid}.mp4", "shot")):
            if (ad.video_dir / name).exists():
                out.append({"sid": sid, "kind": kind, "file": name,
                            "url": f"ads/{ad.ad_id}/video/{name}"})
                break
    return out


def _ad_payload(group: AdGroup, ad) -> dict:
    brief = ad.read_brief()
    script = ad.read_script()
    sc = brief.get("style_contract") or script.get("style_contract") or {}
    return {
        "id": ad.ad_id,
        "name": brief.get("name", ad.ad_id),
        "direction": brief.get("direction", ""),
        "duration_target_s": brief.get("duration_target_s", 30),
        "style_input": brief.get("style", ""),
        "style_contract": sc,
        "status": brief.get("status", "draft"),
        "script": script,
        "gates": {
            "script": _gate_state(ad.dir, "script", group.cfg),
            "video": _gate_state(ad.dir, "video", group.cfg),
        },
        "videos": sorted(
            p.name for p in ad.video_dir.glob("*.mp4")) if ad.video_dir.exists() else [],
        "shot_videos": _shot_videos(ad, script),
        "reviews": ad.reviews_dir.exists(),
        "activity": ACTIVITY.get(ad.ad_id, {}),
        "action": _status(ACTIONS, ad.ad_id),
    }


def _status(store, key: str) -> dict:
    s = store.get(key, {})
    return {"state": s.get("state", "idle"), "detail": s.get("detail", ""),
            "done": s.get("done", 0), "total": s.get("total", 0)}


def _creator_ref_src(group: AdGroup) -> str:
    """Media-relative path of the image shown as the creator identity.

    A generated creator shows its latest rendered ref; an uploaded photo shows
    ref.png. Empty when neither exists yet.
    """
    creator = group.read_creator()
    if creator.get("source") == "generated":
        refs = group.creator_dir / "refs"
        if refs.exists():
            imgs = sorted(refs.glob("*.png"))
            if imgs:
                return f"creator/refs/{imgs[-1].name}"
    return "creator/ref.png" if group.creator_ref_path.exists() else ""


def _group_payload(cfg, group: AdGroup) -> dict:
    product = group.read_product()
    creator = group.read_creator()
    return {
        "id": group.group_id,
        "name": group.read_group().get("name", group.group_id),
        "brief": group.read_group().get("brief", ""),
        "brand": group.read_brand(),
        "product": product,
        "product_gate": _gate_state(group.dir, "product", cfg),
        "creator": creator,
        "creator_gate": _gate_state(group.creator_dir, "creator", cfg),
        "voice_gate": _gate_state(group.creator_dir, "voice", cfg),
        "creator_ref": _creator_ref_src(group),
        "creator_voice": "voice.wav" if group.creator_voice_path.exists() else "",
        "creator_action": _status(ACTIONS, f"{group.group_id}.creator"),
        "product_action": _status(ACTIONS, f"{group.group_id}.product"),
        "ideas": group.read_ideas().get("ideas", []),
        "ideas_action": _status(ACTIONS, f"{group.group_id}.ideas"),
        "uploads": [p.name for p in _intake.list_uploads(group)],
        "ads": [_ad_payload(group, ad) for ad in group.list_ads()],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    cfg = None

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ---- routing ----

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/":
            self._send_html()
        elif path == "/api/state":
            self._send_json(self._state())
        elif path == "/api/events":
            self._send_sse()
        elif path.startswith("/media/"):
            self._send_media(parsed.path)
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            if path == "/api/action":
                ok = self._handle_action()
                if ok:
                    _bus.notify()
            else:
                self._send_json({"error": f"unknown route {path}"}, status=404)
        except Exception as exc:
            log.exception("api error")
            self._send_json({"error": str(exc)}, status=500)

    # ---- helpers ----

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if "application/json" in self.headers.get("Content-Type", ""):
            try:
                return json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return {}
        # Plain x-www-form-urlencoded fallback (text fields only).
        from urllib.parse import parse_qs as _pq
        try:
            return {k: v[0] for k, v in _pq(raw.decode("utf-8")).items()}
        except Exception:
            return {}

    def _send_html(self):
        data = _HTML.read_bytes() if _HTML.exists() else b"<h1>dashboard.html missing</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj, status=200):
        data = _json(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return status < 400

    def _send_sse(self):
        """Long-lived Server-Sent Events stream. One handler thread per client."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = _bus.subscribe()
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                except queue.Empty:
                    data = ": ping\n\n"
                self.wfile.write(data.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError,
                OSError, ValueError):
            pass
        finally:
            _bus.unsubscribe(q)

    def _send_media(self, path):
        cfg = self.cfg
        rel = path[len("/media/"):]
        parts = rel.split("/")
        if len(parts) < 2:
            self._send_json({"error": "bad path"}, 404)
            return
        gid, rest = parts[0], "/".join(parts[1:])
        root = cfg.ad_group_path(gid)
        target = (root / rest).resolve()
        if not str(target).startswith(str(root.resolve())) or not target.exists():
            self._send_json({"error": "not found"}, 404)
            return
        data = target.read_bytes()
        self.send_response(200)
        ctype = "video/mp4" if target.suffix == ".mp4" else "image/png"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---- state ----

    def _state(self) -> dict:
        cfg = self.cfg
        feed = [{"key": k, "detail": v.get("detail", ""), "ts": v.get("ts", 0)}
                for k, v in sorted(ACTIVITY.items(),
                                   key=lambda kv: kv[1].get("ts", 0), reverse=True)[:25]]
        return {
            "groups": [_group_payload(cfg, g) for g in list_ad_groups()],
            "actions": {k: _status(ACTIONS, k) for k in list(ACTIONS)},
            "activity": feed,
        }

    # ---- actions ----

    def _handle_action(self):
        body = self._read_body()
        cfg = self.cfg
        action = body.get("action", "")
        gid = body.get("group", "")
        aid = body.get("ad", "")
        notes = body.get("notes", "") or ""
        group = _group_of(cfg, gid) if gid else None
        ad = _ad_of(group, aid) if (group and aid) else None

        # --- group level ---
        if action == "group.create":
            name = body.get("name", "New Group")
            create_ad_group(name, body.get("brief", ""))
            return self._send_json({"ok": True})

        if action == "group.delete":
            if group is None:
                return self._send_json({"error": "group not found"}, 404)
            delete_ad_group(gid)
            return self._send_json({"ok": True})

        if action == "product.upload":
            data = body.get("data", "")
            filename = body.get("filename", "product.png")
            if isinstance(data, str):
                import base64
                try:
                    data = base64.b64decode(data.split(",", 1)[-1])
                except Exception:
                    return self._send_json({"error": "bad upload data"}, 400)
            _intake.save_upload(group, filename, data)
            return self._send_json({"ok": True})

        if action == "product.normalize":
            start_action(gid + ".product", lambda: _intake.normalize_product(group, cfg=cfg)
                         and f"product normalized ({len(_intake.list_uploads(group))} photo(s))")
            return self._send_json({"ok": True, "started": True})

        if action == "product.set_kind":
            kind = body.get("kind", "")
            start_action(gid + ".product", lambda: _intake.set_product_kind(group, kind, cfg=cfg)
                         and f"product marked {kind}")
            return self._send_json({"ok": True, "started": True})

        if action == "product.revise":
            start_action(gid + ".product", lambda: _intake.revise_product(group, notes, cfg=cfg)
                         and "product revised")
            return self._send_json({"ok": True, "started": True})

        if action == "product.approve":
            approve_gate(group.dir, "product", notes)
            report(gid + ".product", "product approved")
            return self._send_json({"ok": True})

        if action == "product.reject":
            reject_gate(group.dir, "product", notes)
            report(gid + ".product", f"product rejected: {notes}" if notes else "product rejected")
            return self._send_json({"ok": True})

        # --- creator level ---
        if action == "creator.photo":
            data = body.get("data", "")
            filename = body.get("filename", "creator.png")
            if isinstance(data, str):
                import base64
                try:
                    data = base64.b64decode(data.split(",", 1)[-1])
                except Exception:
                    return self._send_json({"error": "bad upload data"}, 400)
            p = group.creator_dir / "photo_upload.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            _creator.set_creator_photo(group, p)
            return self._send_json({"ok": True})

        if action == "creator.remove":
            _creator.clear_creator(group)
            report(gid + ".creator", "creator removed")
            return self._send_json({"ok": True})

        if action == "creator.generate":
            start_action(gid + ".creator", lambda: _creator.generate_creator(group, notes, cfg=cfg)
                         and "creator generated")
            return self._send_json({"ok": True, "started": True})

        if action == "creator.revise_ref":
            start_action(gid + ".creator",
                         lambda: _creator.revise_creator_ref(group, notes, cfg=cfg)
                         and "creator ref regenerated")
            return self._send_json({"ok": True, "started": True})

        if action == "creator.approve":
            approve_gate(group.creator_dir, "creator", notes)
            report(gid + ".creator", "creator approved")
            return self._send_json({"ok": True})

        if action == "creator.reject":
            reject_gate(group.creator_dir, "creator", notes)
            report(gid + ".creator", f"creator rejected: {notes}" if notes else "creator rejected")
            return self._send_json({"ok": True})

        if action == "voice.approve":
            approve_gate(group.creator_dir, "voice", notes)
            report(gid + ".creator", "voice approved")
            return self._send_json({"ok": True})

        if action == "voice.reject":
            reject_gate(group.creator_dir, "voice", notes)
            report(gid + ".creator", f"voice rejected: {notes}" if notes else "voice rejected")
            return self._send_json({"ok": True})

        # --- ad level ---
        if action == "ad.create":
            ad = group.create_ad(body.get("name", "New Ad"), body.get("direction", ""),
                                 int(body.get("duration", 30)), body.get("style", ""))
            return self._send_json({"ok": True, "ad": ad.ad_id})

        if action == "ad.ideas":
            start_action(gid + ".ideas", lambda: _ideate.generate_ideas(group, cfg=cfg)
                         and "ad ideas generated")
            return self._send_json({"ok": True, "started": True})

        if ad is None:
            return self._send_json({"error": "ad not found"}, 404)

        if action == "script.generate":
            start_action(ad.ad_id, lambda: _scriptgen.generate_script(group, ad, cfg=cfg)
                         and f"script generated ({len(ad.read_script().get('shots', []))} shots)")
            return self._send_json({"ok": True, "started": True})

        if action == "script.revise":
            start_action(ad.ad_id, lambda: _scriptgen.revise_script(group, ad, notes, cfg=cfg)
                         and "script revised")
            return self._send_json({"ok": True, "started": True})

        if action == "script.approve":
            approve_gate(ad.dir, "script", notes)
            report(ad.ad_id, "script approved")
            return self._send_json({"ok": True})

        if action == "script.reject":
            reject_gate(ad.dir, "script", notes)
            report(ad.ad_id, f"script rejected: {notes}" if notes else "script rejected")
            return self._send_json({"ok": True})

        if action == "video.render":
            start_action(ad.ad_id, lambda: _stitch.build_video(group, ad, cfg=cfg))
            return self._send_json({"ok": True, "started": True})

        if action == "video.approve":
            approve_gate(ad.dir, "video", notes)
            report(ad.ad_id, "video approved")
            return self._send_json({"ok": True})

        if action == "video.reject":
            reject_gate(ad.dir, "video", notes)
            report(ad.ad_id, f"video rejected: {notes}" if notes else "video rejected")
            return self._send_json({"ok": True})

        return self._send_json({"error": f"unknown action {action}"}, 404)


def serve(port: int = 8126, bind: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Start the dashboard server (blocking)."""
    cfg = get_config()
    DashboardHandler.cfg = cfg
    server = ThreadingHTTPServer((bind, port), DashboardHandler)
    log.info("Marketing Studio dashboard on http://%s:%d", bind, port)
    print(f"Marketing Studio dashboard -> http://{bind}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return server
