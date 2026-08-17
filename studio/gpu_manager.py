"""Per-node exclusive-GPU manager.

Only one GPU-heavy service is resident at a time on a node. Lifecycle is
portable and config-driven: LM Studio via the `lms` CLI, ComfyUI via its
portable run script, TTS via a configured venv. If a service is not configured
or its binary is missing, acquire() still works (stub mode) so the pipeline is
testable before hardware is provisioned. Pattern ported from the anime studio.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from enum import Enum
from typing import Iterator

from .config import get_config

log = logging.getLogger(__name__)


class ServiceType(Enum):
    LLM = "llm"
    TTS = "tts"
    COMFYUI = "comfyui"
    STT = "stt"


VRAM_BUDGETS = {
    ServiceType.LLM: 24000,
    ServiceType.TTS: 7000,
    ServiceType.COMFYUI: 12000,
    ServiceType.STT: 3000,
}


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20)
    except subprocess.TimeoutExpired:
        log.warning("[gpu] subprocess timed out: %s", " ".join(str(c) for c in cmd))
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr="timeout")
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr="not found")


class _ProcessGpuLock:
    """Cross-process lock for the machine's single shared GPU."""

    def __init__(self, path):
        self.path = path
        self._file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        if self._file.seek(0, 2) == 0:
            self._file.write(b"0")
            self._file.flush()
        self._file.seek(0)
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.5)
        else:
            import fcntl
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)

    def release(self) -> None:
        if self._file is None:
            return
        try:
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None


class GPUManager:
    def __init__(self, cfg=None):
        self.cfg = cfg or get_config()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._current: ServiceType | None = None
        self._current_model: str | None = None
        self._holders = 0
        self._comfy_procs: dict[str, subprocess.Popen] = {}
        self._process_lock = _ProcessGpuLock(self.cfg.root / ".gpu-manager.lock")
        self._local = threading.local()

    @property
    def current(self) -> ServiceType | None:
        with self._lock:
            return self._current

    def _load(self, service: ServiceType, model: str | None = None) -> None:
        if service == ServiceType.LLM:
            self._load_llm(model)
        elif service == ServiceType.COMFYUI:
            self._load_comfyui()
        elif service == ServiceType.TTS:
            self._load_tts()
        else:
            log.info("[gpu] load %s (stub; VRAM ~%d MB)", service.value, VRAM_BUDGETS[service])

    def _unload(self, service: ServiceType | None) -> None:
        if service is None:
            return
        if service == ServiceType.LLM:
            self._unload_llm()
        elif service == ServiceType.COMFYUI:
            self._unload_comfyui()
        else:
            log.info("[gpu] unload %s (stub)", service.value)

    # ---- LM Studio (portable `lms` CLI) ----

    def _load_llm(self, model: str | None = None) -> None:
        lms = self.cfg.lms_cli()
        port = self.cfg.get("env", "lmstudio", {}).get("server_port", 1234)
        ctx = self.cfg.get("env", "lmstudio", {}).get("context", 131072)
        ratio = self.cfg.get("env", "lmstudio", {}).get("gpu_ratio", "max")
        gpu = "max" if ratio in (None, "", "max", "auto") else str(ratio)
        if not _port_open(port):
            _run([lms, "server", "start", "--port", str(port), "--cors"])
            time.sleep(4)
        model = (model
                 or self.cfg.get("llm", "roles", {}).get("director")
                 or self.cfg.get("llm", "model")
                 or self.cfg.get("env", "lmstudio", {}).get("models", {}).get("director", ""))
        # The vision model doesn't need the huge main-model context; a smaller
        # KV budget keeps it loadable on the same card.
        describer = self.cfg.get("llm", "roles", {}).get("describer", "") or ""
        if model and describer and model == describer:
            ctx = self.cfg.get("env", "lmstudio", {}).get("vision_context", 32768)

        import httpx
        # NON-DESTRUCTIVE: if the model is already loaded and serving, do nothing.
        # `lms load` on this setup is flaky (destructive unload+reload, canceled
        # loads) and the loaded model persists across processes, so reloading a
        # healthy model only risks wedging the server. The serving check is cached
        # briefly so a burst of LLM calls doesn't hammer the server with probes.
        now = time.time()
        if model and now < getattr(self, "_llm_ok_until", 0.0):
            return
        if model and self._llm_serves(httpx, port, model):
            self._llm_ok_until = now + 90.0
            return
        # Safety eject: evict any ComfyUI models from VRAM before loading LLM.
        self._eject_comfy()
        if not model:
            log.info("[gpu] LLM: no director model configured in env.yaml; using existing server")
            return
        _run([lms, "unload", "--all"])
        time.sleep(1)
        # `lms load` is async (progress spinner). Redirect it so it never
        # pollutes the pipeline logs, then wait for the API to actually serve it.
        subprocess.Popen([lms, "load", model, "--gpu", gpu, "-c", str(ctx),
                          "--parallel", "1", "-y"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 420
        while time.time() < deadline:
            if self._llm_serves(httpx, port, model):
                # Settle: let the engine finish warming so the first real
                # request doesn't race the tail of the load.
                time.sleep(2)
                return
            time.sleep(5)
        log.warning("[gpu] LLM load: model %s readiness not confirmed", model)

    @staticmethod
    def _llm_serves(httpx, port: int, model: str) -> bool:
        """True when a tiny completion on `model` succeeds (real serving check)."""
        probe = {"model": model,
                 "messages": [{"role": "user", "content": "hi"}],
                 "max_tokens": 4}
        try:
            resp = httpx.post(f"http://127.0.0.1:{port}/v1/chat/completions",
                              json=probe, timeout=60)
            return resp.status_code == 200
        except Exception:
            return False

    def _unload_llm(self) -> None:
        _run([self.cfg.lms_cli(), "unload", "--all"])
        time.sleep(1)

    # ---- ComfyUI (portable tree per role) ----

    def _comfy_cfg(self) -> dict:
        which = "krea2" if not self.cfg.is_renderer() else "h3"
        return self.cfg.comfy_instance(which)

    def _comfy_instances(self) -> list[dict]:
        return list((self.cfg.get("env", "comfyui", {}) or {}).values())

    def _eject_comfy(self) -> None:
        """Offload models on every configured ComfyUI instance (frees VRAM)."""
        for inst in self._comfy_instances():
            self._free_comfy(inst)

    def _free_comfy(self, inst: dict) -> None:
        """POST /free to one ComfyUI instance (offload its models)."""
        port = int(inst.get("port", 8188) or 0)
        if not port or not _port_open(port):
            return
        try:
            url = inst.get("url") or f"http://127.0.0.1:{port}"
            import httpx
            with httpx.Client(timeout=30.0) as client:
                client.post(f"{url}/free",
                            json={"unload_models": True, "free_memory": True})
        except Exception:
            log.debug("[gpu] ComfyUI /free failed on :%s", port, exc_info=True)

    def _load_tts(self) -> None:
        """Free VRAM for the TTS model: eject LLM + every ComfyUI instance.

        ComfyUI's /free unloads asynchronously, so wait for real free VRAM before
        the TTS runner process starts, or its model load can OOM-crash. The
        synthesis runs in a separate process (studio/tts_runner.py with the TTS
        venv); when that subprocess exits it releases VRAM, so there is no explicit
        unload step.
        """
        self._unload_llm()
        self._eject_comfy()
        self._wait_free_vram(need_mb=6000, timeout_s=60)
        log.info("[gpu] TTS: VRAM ~%d MB (model loads in the runner process)",
                 VRAM_BUDGETS[ServiceType.TTS])

    @staticmethod
    def _free_vram_mb() -> int | None:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                                  "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10)
            return int(out.stdout.strip().splitlines()[0])
        except Exception:
            return None

    def _wait_free_vram(self, need_mb: int = 6000, timeout_s: int = 60) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            free = self._free_vram_mb()
            if free is None:
                return  # can't measure; proceed
            if free >= need_mb:
                return
            time.sleep(2)
        log.warning("[gpu] VRAM did not reach %d MB free within %ds", need_mb, timeout_s)

    def _load_comfyui(self) -> None:
        self._unload_llm()
        inst = self._comfy_cfg()
        port = int(inst.get("port", 8188))
        # The two instances share one card: free every OTHER instance's models so
        # the target gets the full VRAM (e.g. h3's 14.6GB CLIP needs it).
        for other in self._comfy_instances():
            oport = int(other.get("port", 8188) or 0)
            if oport and oport != port:
                self._free_comfy(other)
        if _port_open(port):
            log.info("[gpu] ComfyUI already up on :%s", port)
            self._wait_free_vram(need_mb=6000, timeout_s=45)
            return
        tree = inst.get("dir", "")
        run_script = inst.get("run", "run_nvidia_gpu.bat")
        if not tree:
            log.info("[gpu] ComfyUI: no portable tree configured in env.yaml (stub)")
            return
        from pathlib import Path
        tree_p = Path(tree)
        bat = tree_p / run_script
        if not bat.exists():
            log.warning("[gpu] ComfyUI run script missing: %s", bat)
            return
        proc = subprocess.Popen(
            ["cmd", "/c", str(bat)],
            cwd=str(tree_p),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        self._comfy_procs[str(port)] = proc
        for _ in range(int(self.cfg.get("comfy", "startup_retries", 30))):
            time.sleep(2)
            if _port_open(port):
                return
        log.warning("[gpu] ComfyUI startup on :%s not confirmed", port)

    def _unload_comfyui(self) -> None:
        inst = self._comfy_cfg()
        port = int(inst.get("port", 8188))
        # Offload models from VRAM regardless of who started the instance.
        if _port_open(port):
            try:
                url = inst.get("url") or f"http://127.0.0.1:{port}"
                import httpx
                with httpx.Client(timeout=30.0) as client:
                    client.post(f"{url}/free",
                                json={"unload_models": True, "free_memory": True})
            except Exception:
                log.debug("[gpu] ComfyUI /free failed (already gone?)", exc_info=True)
        # Stop only instances this manager spawned itself. Externally-started
        # ComfyUI (via its own batch file) is left running; its models unload
        # via /free above and reload lazily on the next request.
        if bool(self.cfg.get("comfy", "manage_lifecycle", True)):
            proc = self._comfy_procs.pop(str(port), None)
            if proc and proc.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=30)
        time.sleep(1)

    @contextmanager
    def acquire(self, service: ServiceType, model: str | None = None) -> Iterator[None]:
        """Exclusive GPU access for `service`. Blocks until the GPU is free.

        Re-entrant per thread: a nested acquire from a thread that already holds
        the GPU runs without re-acquiring (avoids self-deadlock).
        """
        if getattr(self._local, "depth", 0) > 0:
            self._local.depth += 1
            try:
                yield
            finally:
                self._local.depth -= 1
            return
        with self._condition:
            while self._holders and not (
                    service == ServiceType.LLM
                    and self._current == ServiceType.LLM
                    and self._current_model == model):
                self._condition.wait()
            first_holder = self._holders == 0
            if first_holder:
                self._process_lock.acquire()
                try:
                    self._load(service, model)
                    self._current = service
                    self._current_model = model
                except Exception:
                    self._process_lock.release()
                    raise
            self._holders += 1
        self._local.depth = 1
        try:
            yield
        finally:
            self._local.depth = 0
            with self._condition:
                self._holders -= 1
                if self._holders == 0:
                    try:
                        self._unload(self._current)
                    finally:
                        self._current = None
                        self._current_model = None
                        self._process_lock.release()
                        self._condition.notify_all()


_default: GPUManager | None = None


def get_gpu_manager(cfg=None) -> GPUManager:
    global _default
    if _default is None:
        _default = GPUManager(cfg)
    return _default
