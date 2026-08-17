# HANDOFF — Marketing Studio

Handoff for an agent working on `C:\Users\Chad\PycharmProjects\MarketingStudio`.

A local-first, dashboard-driven UGC ad studio. Product photos + a short direction in;
finished short-form ads out, rendered with a creator on camera (local H3 video).
Architecture mirrors the anime studio's plumbing; the domain and all output are photoreal
UGC marketing — nothing anime carries over. See `DESIGN.md` for the full spec.

---

## 1. Machines / infra (same as the anime studio)

- **BEAST5 (this machine):** LM Studio desktop app (127.0.0.1:1234), Krea 2 ComfyUI
  `D:\anime-h3` `run_krea2_gpu.bat` on **8190**, H3 ComfyUI `D:\anime-h3` `run_h3.bat` on **8188**,
  ffmpeg at `C:/Program Files/Kdenlive/bin/ffmpeg.exe`, Qwen3-TTS in the LanguageLearner venv.
- **Models:** LLM = `gemma-4-e4b-uncensored-hauhaucs-aggressive` (loaded at 131072 ctx, 6.33 GB).
  It is multimodal — vision works in-model, so the `describer` role uses gemma too (single model,
  no model-switching).

## 2. Status (tested 2026-08-14)

- **Config updated** to the real machine (`config/llm.yaml`, `config/comfy.yaml`, `config/env.yaml`).
- **Gates 1–3 VALIDATED against the real model.** Product intake (vision normalize) produced a real
  canonical contract; creator (photo identity + silent TTS voice) works; the chunked script
  generation produced a complete 4-shot / 30s ad with genuine UGC copy, a coherent hook→convert
  arc, and hook/story/runtime reviews. Offline smoke test (`tests/smoke.py`, fake LLM) is green,
  including the dashboard HTTP layer.
- **Gates 4–5 (storyboard / H3 video) not exercised** — both ComfyUI instances were down. Start them
  (`run_krea2_gpu.bat` on 8190, `run_h3.bat` on 8188) to test keyframes + ref2va + the retake-stitch
  orchestrator.

## 3. LLM stability on this setup (READ FIRST)

The local LM Studio server **degrades under sustained multi-request load**: after a handful of
sequential calls it returns `{"error":"Model unloaded."}` (400), `400 Bad Request`, or
`WinError 10054` connection resets, then recovers. Mitigations already in the code:

- **Non-destructive loader** (`gpu_manager._load_llm`): probes the API first; only unloads+loads if
  the model isn't actually serving. Serving check is cached 90s.
- **Self-healing retries** (`clients/lmstudio.py`): on failure the loader's serving cache is
  invalidated so the next retry re-probes and reloads; backoff grows per attempt.
- **No streaming** — gemma's SSE streaming is broken on this stack (drops content after ~13 chars);
  all calls are non-streaming. `on_progress` fires once at the end.
- **Partial revisions** — the writers'-room revision returns only changed shots (merged by id),
  so gemma never has to re-emit the full script (it truncates on long JSON output).

Still, the server wedging **cannot be fully papered over in code**. If real runs keep failing:
- Restart the LM Studio app (kill `LM Studio.exe`, relaunch) and reload gemma.
- Consider loading gemma at a **smaller context** in the LM Studio app UI (the `lms -c` flag is
  ignored on this setup) — memory pressure at 131072 ctx is the likely cause of mid-run evictions.
- The `lms` CLI cannot reliably swap models here (loading qwen while gemma is resident fails with
  "Operation canceled"). Hence single-model (gemma for text + vision).

## 4. Known issues / decisions

- Vision normalize worked via gemma after the server was restarted clean; qwen3-vl-8b is available
  but not used (would require it to be the sole loaded model).
- The `lms load` spinner used to pollute stdout; loader now redirects it to DEVNULL.
- `lms unload --all` sometimes reports "No models to unload" while a model is actually loaded
  (server/CLI state skew) — restart the app to clear.

## 5. How to run

```
.venv\Scripts\python.exe studio.py          # dashboard -> http://127.0.0.1:8126
.venv\Scripts\python.exe tests\smoke.py     # offline pipeline + dashboard test
```

## 6. Next steps

1. Start Krea 2 (8190) + H3 (8188) ComfyUI; test storyboard keyframes (Gate 4) and per-shot H3
   ref2va + retake-stitch (Gate 5) on the `glow-skincare` ad group.
2. Wire the real Qwen3-TTS voice (config already points at LanguageLearner; `tts_runner.py` path in
   env.yaml `env.tts.runner` is still empty).
3. If LM Studio keeps wedging, load gemma at a smaller context in the app UI.
