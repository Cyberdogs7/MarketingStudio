# Marketing Studio — Design & Specification

**Status:** Draft v0.2
**Date:** 2026-08-14
**Owner:** Chad
**Goal:** A local-first, dashboard-driven **UGC ad studio in a box**. The user creates an **Ad
Group** (brand + product + creator identity + voice), then generates any number of **Ads** from it —
each ad is a finished TikTok / Instagram-style short, with its **own direction and duration target**,
rendered with the same creator on camera speaking about the product.

The **architecture pattern** mirrors the anime studio repo (`anime/`); the **creative domain and
every pixel of output are photoreal UGC marketing** — no anime content, no anime style, no anime
prompts carry over. Krea 2 (image) and MiniMax H3 (video) are SOTA realism models and are used for
photoreal output only.

This document reviews how the anime project does script creation, reference images, and video
generation (as the reference architecture), then specifies the UGC studio that mirrors its *plumbing*
with entirely different domain logic.

---

## 1. Executive summary

Studio metaphor, remapped to ad account structure:

| Real role | Reference (anime) | UGC studio |
|---|---|---|
| Account / brand | Show bible | **Ad Group** — brand rules, product, creator, voice |
| Creative | Episode | **Ad** — one short; own direction + duration |
| Client brief | Episode outline | **Ad brief** (direction, vibe, target, duration) |
| Product designer | Character sheets | **Product intake** (uploaded photo → canonical description) |
| Casting | Character refs + voices | **Creator** (uploaded photo, or generated ref + voice) |
| Copywriter | Showrunner LLM | **Monologue writer** (hook + story shape + persona + beats) |
| Storyboard artist | Krea 2 keyframes | **Krea 2 keyframes** (photoreal UGC) |
| Shot lead | MiniMax H3 ref2va | **MiniMax H3 ref2va** (photoreal, same workflow) |
| Continuity | Retake stitch (unbuilt) | **H3 Retake Stitch orchestrator** (continuous-take assembly) |
| QC | Consistency vision review | **Frozen-frame / identity QC** (creator + product) |
| Editor | ffmpeg assembly | **ffmpeg hard-cut concat** (for scene changes) |
| Studio manager | Dashboard + gates | **Dashboard + gates** (all UX lives here) |

**Ad account hierarchy (the domain model):**

```
Ad Group  (reusable identity, approved once)
├── brand.json        brand name, tone of voice, approved-claims list (verbatim contract)
├── product.json      uploaded photo(s) → canonical product_description, tier, category
├── creator/          identity ref (photo wins) + persona + TTS voice sample
└── Ads  (each a full run: brief → script → storyboard → video → stitch)
    ├── ad_01         direction: "…", duration: 30s, style: "Authentic Bathroom GRWM"
    ├── ad_02         direction: "…", duration: 15s, style: "Clean Minimal Tech"
    └── …
```

One influencer, one product, one brand voice — **many ads**, each independently **directed,
length-targeted, and styled**. The expensive identity assets (product, creator, voice) are built once
per group and reused verbatim by every ad; the **visual style is established per ad generation**, so
the same group can produce a gritty handheld vlog, a clean minimal tech review, and a warm lifestyle
GRWM from the same identity.

The defining product: **the "super-detailed prompting for the video creator" is the core.** The user
supplies only **product photos + a short direction**; the system owns the full UGC craft rule set
(hook patterns, story shapes, persona registers, anti-slop, product staging / angle / scale / hand
rules, camera framing) and the deterministic MiniMax prompt compiler.

---

## 2. Review of the reference projects

### 2.1 The anime studio — reference architecture (not content)

All three pillars were reviewed in `C:\Users\Chad\PycharmProjects\anime`. We reuse the *plumbing
patterns*; nothing domain-specific is adopted.

**Script creation** (`studio/planner.py`, `studio/scriptgen.py`, `studio/prompts.py`):
- **Chunked, single-responsibility LLM passes.** Every stage is one small local-LLM call (LM Studio,
  OpenAI-compatible, `response_format=json_object`) returning strict JSON, checkpointed to disk for
  resume.
- Development (direction/synopsis) → a show-specific **prompt template** with `{{TOKEN}}`
  placeholders filled with live state → **outline** (skeleton pass + per-batch beats pass) → **scene
  details** → **per-scene shots** as a *chain* of focused passes (`blocking → camera → action →
  references → costumes → soundscape → dialogue`). Each later pass merges only its own fields into
  the draft (`_apply_pass`), keyed by id.
- **Review loops** (writers'-room reviewers + a deterministic runtime check); failing output is
  revised up to `max_revisions` rounds.
- **Human approval gates**; rejection notes persist as durable constraints injected as ABSOLUTE rules
  into the next generation.

**Reference images** (`studio/casting.py`, `studio/storyboard.py`, `studio/comfy_workflows.py`):
- Identity sheets carry an `appearance_canonical` string; a **ref pass** diffs a structured cast
  against assets that already have a real ref image, then renders missing ones via **Krea 2**.
- Variants via **Qwen-Image-Edit** (identity-preserving edits of a base ref); a `refs.json` registry
  holds variants, prompts, seeds, and an **approval list**; unapproved refs block generation.
- **Storyboard keyframes** per shot via Krea 2 + ref chaining; **consistency QC** uses a vision LLM
  to review keyframes for identity/text defects and rewrites + regenerates up to N rounds.

**Video generation** (`studio/render.py`, `studio/h3.py`):
- One **MiniMax H3** `ref2va` ComfyUI job per shot; refs are sockets (`LoadImage → ref_image_N`,
  `LoadAudio → ref_audio_N`) auto-labeled `<Picture N>` / `<Audio N>`.
- A **deterministic prompt compiler** emits the six-section MiniMax notation
  (`subject_definitions / summary / retention_analysis / detailed_description / overall_soundscape /
  non_diegetic_music`) binding refs to `<Subject N>`, voice to `<Audio N>`, dialogue to
  `<d>[English] …</d>`.
- 1-second previews run the *same* workflow for cheap QC; a GPU manager serializes image vs video
  VRAM; background threads report progress.

### 2.2 The Higgsfield UGC creator — the domain example

`get_workflow_instructions({workflow:"ugc-flow"})` defines the target creative product; its rule sets
become the **UGC rule packs** in §7:

- **Product intake is a contract.** Normalize ONCE into a canonical `product_description` (shape,
  material, hand-relative size, mechanism anatomy, absent-feature negatives, label handling), plus
  `tier` (luxury/premium/drugstore) and `category`; reused verbatim everywhere; claims only from an
  approved list.
- **Creator identity locked** for the whole run, never regenerated.
- **Monologue craft**: word-density budgets, one voice archetype per register (NATURAL default /
  HYPED / CALM), story-mode default with a 17-shape menu, hook-pattern menu (H1–H8), hard anti-slop
  (banned openers/words, first-word constraint, claim-without-concrete), performed dialogue, at most
  one peak per clip.
- **Visual staging**: per-slot POV / distance-band / action diversity (anti-morph), hand allocation
  (exactly two hands), product Angle Lock + realistic scale, one hero product, safe interaction
  verbs, label/wordmark treatment, iPhone-photo realism, hard cuts.

### 2.3 Adopt vs adapt — and the hard "nothing anime" rule

| Adopt wholesale (port plumbing) | Adapt (UGC domain) | Deliberately drop |
|---|---|---|
| Config loader (`config.py`) | Ad Group / Ads account model (§5) | Plotlines / continuity engine |
| LM Studio client | Product intake contract (§6.1) | Multi-character casting |
| ComfyUI client + H3 ref2va workflow | Creator = one identity (§6.2) | Costume variants / wardrobe |
| Keyframe workflow (`image_keyframe.json`) | UGC rule packs → prompt injection | Recurring-object refs |
| GPU manager, `snap_duration` grid | Story-shape / hook / persona craft | Episodic runtime targets |
| Approval-gate + dashboard patterns | Frozen-frame QC (creator + product) | Multi-voice TTS |
| Review-loop pattern | Deterministic MiniMax prompt compiler | Anime content policy model |
| **H3 Retake Stitch workflow builder** | **Stitch orchestrator** (§8) — new | — |

**Hard rule — nothing anime copies over.** No anime-style prompts, no "anime cinematic keyframe"
wording, no 2D-anime style guide, no anime checkpoint/CLIP/lora references beyond the shared H3/Krea
2 base models, no anime genre/tone/maturity config. All keyframe and video prompts are photoreal UGC
per the rule packs; the reviewer rubrics target realism and hook effectiveness, not series
consistency. The only thing "copied" is the orchestration pattern (config, clients, gates, chain
passes, review loop, dashboard model) and the H3/Krea 2 engine wiring — both domain-neutral.

### 2.4 H3 clip stitching — what exists, what we build

The anime project **did not complete** end-to-end H3 rendering (HANDOFF §6 lists it as unwired). What
*does* exist and is proven:

- `build_h3_retake_workflow` (`studio/h3.py`) drives **`MiniMaxH3RetakeStitchCS`**. Its docstring:
  *"When retake_start + retake_length reaches past the base video's end, the range is a true
  extension (head + new content, no tail)."* — i.e. it can **append** new content to a video.
- A CLI exercised it (`shot --retake --start end` = append after the video), and `clients/comfy.py`
  already has `upload_video` for feeding the base video back in.

What we build in MarketingStudio (the missing orchestrator):
- **Continuous-take stitch**: shot 1 renders fresh via `ref2va`; shots 2..N render as *retake
  extensions* of the previous stitched output (`retakeStart = current end frame`,
  `retakeLength = next shot's frames`, `base_video = previous stitched MP4`), so a 15–60 s ad becomes
  **one continuous MP4** with the creator/lighting/room held across cuts — the H3-native replacement
  for Seedance's internal hard-cut boards.
- **ffmpeg hard-cut concat** as the fallback for *intentional* discontinuities (location change,
  time jump) — decided per shot by a `continuous` flag on the shot's staging.
- The stitch is part of the ad render stage, QC'd on the assembled video, and resumable per shot.

---

## 3. Goals and non-goals

### Goals
1. **Dashboard-only UX.** Every input, gate, and review happens in the browser.
2. **Product photos + direction in, finished short out.** The system writes the entire UGC craft:
   monologue, staging, keyframes, video + stitch prompts. The human approves/rejects, never authors.
3. **Ad Group → many Ads.** One influencer/product/brand; each ad gets its **own direction,
   duration target, and style** and is a full independent run. Style is established at ad
   generation time and flows through script, keyframes, video, and review.
4. **Identity consistency** of creator (face) and product (angle, label, scale) across every shot and
   every ad, enforced by shared refs + vision QC.
5. **Continuous-take video via H3 stitch** (with ffmpeg hard cuts for scene changes).
6. **Local-first** — LM Studio, Krea 2, H3, TTS, ffmpeg. No hosted generative API in the content
   path.
7. **Crash-safe, resumable, auditable** — checkpointed stage state per ad; artifacts + review trail.
8. **Photoreal output only.** Krea 2 + H3 render realism; nothing anime.

### Non-goals (v0)
- Publishing integrations, analytics, or ad-account syncing (Meta/TikTok APIs).
- Caption/timing burn is opt-in post-processing, never in-model text.
- Lip-sync post-processing — H3 generates video+audio jointly; the creator's TTS voice sample is an
  `<Audio N>` reference so mouth motion is produced in-model.
- Series calendars / content scheduling / A/B testing.
- Product URL intake (local file upload only in v0).

---

## 4. Design decisions (settled)

| Decision | Choice | Rationale |
|---|---|---|
| Video backend | **Local H3 (MiniMax ref2va + Retake Stitch)** | Same engine as reference; offline; photoreal; SOTA for realism. |
| Image backend | **Krea 2 (local ComfyUI)** for keyframes + generated creator refs | SOTA realism; same workflow as reference. |
| LLM | **Local LM Studio**, per-role models, JSON outputs | Same as reference; privacy + no per-token cost. |
| Product intake | **Local file upload only** | Matches "UPLOAD product images". |
| UX | **All through the dashboard** | One HTTP dashboard hosts every gate, upload, approve/reject, progress, review. |
| Creator identity | Uploaded photo **wins**; else generated via Krea 2 | Matches the ugc-flow "a photo IS the creator" hard gate. |
| Account model | **Ad Group → Ads** (identity once, many creatives) | Same influencer creating many ads, each with its own direction + duration + style. |
| Style | **Per-ad style contract** (named preset or free-form → normalized) | Style is a property of the ad, not the group; restated verbatim through every stage. |
| Aspect / duration | 9:16 vertical; ad target 15–60 s; shots snapped to the H3 grid | TikTok/Instagram short form. |

---

## 5. Ad Group / Ad data model

```
ad_groups/<group_id>/
  group.json            # name, brand name, tone-of-voice, status
  brand.json            # approved-claims list (verbatim), banned-claims, audience notes
  product.json          # G1: category, tier, usage_mechanic, opening_mechanic,
                        #     canonical product_description, absent_features, label_notes
  product_approval.json # gate state
  creator/
    creator.json        # G2: persona_sentence, register, appearance_canonical
    ref.png             # uploaded photo OR generated ref (the identity)
    refs/refs.json      # registry (base variant, prompt, approved)
    voice.wav           # TTS voice sample (<Audio N> source)
  ads/
    ad_01/
      brief.json        # direction text + duration_target_s + style (+ optional overrides)
      script.json       # G3: register, hook_pattern, story_shape, persona_sentence,
                        #     shots[] {id, duration_s, continuous, camera, action,
                        #              dialogue[], staging, soundscape, music}
      storyboard/       # G4: <sid>.png keyframes + reviews/consistency.json
      video/            # G5: <sid>.mp4 previews, stitched shots, final.mp4, qc.json
      reviews/          # per-gate reviewer notes
    ad_02/ …
  uploads/              # raw product photos (shared)
```

Per-ad state is fully independent and resumable; every ad draws its identity contract from the
group's approved `product.json` / `creator/` verbatim.

---

## 6. Pipeline stages and gates

Gates are approve/reject; rejection notes become durable constraints for that gate's regeneration
(mirror of the reference's director notes).

### Group gates (once per ad group)

**G0 — Ad Group.** Name, brand, tone of voice, optional audience note. (Approved once.)

**G1 — Product intake** (`studio/intake.py`)
- Dashboard file upload → `uploads/`; verified as an image.
- **Normalization LLM** (`prompts.product_normalize_prompt`) reads the photo(s) and returns strict
  JSON: `{category, tier (luxury|premium|drugstore), usage_mechanic, opening_mechanic, key_visuals,
  label_notes, canonical_product_description, absent_features}`.
- The canonical description follows the staging contract: shape, material, color, hand-relative size
  ("palm-sized, ~12 cm tall" — never object comparisons), mechanism anatomy, absent-feature negatives
  ("cordless, no buttons"), label handling, one honest imperfection.
- Claims come only from the brand's approved list (exact strings, verbatim) — never invented.
- Persisted as `product.json`; approve / reject / re-normalize with notes.

**G2 — Creator** (`studio/creator.py`)
- **Uploaded photo** = the identity; stored as `creator/ref.png` verbatim. The LLM still writes the
  persona/register, but the appearance is never re-described.
- **No photo** → LLM writes a photoreal `appearance_canonical` (un-retouched, per register rules);
  Krea 2 renders `creator/refs/refs.json` + base ref.
- **Voice**: TTS renders `creator/voice.wav` for the persona (one talent voice per group).
- Approve/reject image and voice separately.

### Per-ad gates (each ad is a full run)

**A1 — Ad brief.** Direction text + `duration_target_s` (e.g. 15 / 30 / 45 / 60) + **style**.
Optional overrides: setting, wardrobe, mood, product close-ups, location sequence.

**Style contract (per ad, decided here once).** The style is either a **named preset** from the
catalog (`rules/style.md`) — e.g. *Authentic Bathroom GRWM*, *Clean Minimal Tech*, *Warm Morning
Lifestyle*, *Gritty Handheld Vlog*, *Calm Luxury Aesthetic*, *Bright Studio Product* — or **free-form
direction**, which the LLM normalizes into the same shape. Either way it resolves to a single
structured contract, stored on the ad and **restated verbatim** at every downstream stage:

```
style_contract = {
  "name": "Gritty Handheld Vlog",
  "register": "NATURAL",                    # drives the persona tier + monologue energy
  "visual_look": "raw handheld vlog",        # framing feel, texture, grade
  "lighting": "single warm practical lamp, high shadows",
  "color_grade": "muted, low-contrast, slight desat",
  "camera_texture": "mild handheld shake, iPhone grain, deep focus",
  "setting_defaults": ["bedroom", "desk", "bathroom"],
  "wardrobe_anchor": "oversized hoodie, no logos",
  "music_feel": "low lo-fi bed, drops out under the line",
}
```

The contract drives: the register/persona selection in the direction pass, the keyframe visual rules
(`rules/visual.md`), the shot staging and video prompts, and the reviewer rubric. Two ads in one
group may differ arbitrarily in style — identity (face, product, voice, brand claims) stays locked,
style does not.

**A2 — Script / monologue** (`studio/scriptgen.py`, `studio/prompts.py`)
Chunked, mirroring the reference planner but flat (no episodes), with the group's identity contract
injected:

1. **Direction pass** (`prompts.monologue_direction_prompt`): brief + product.json + creator persona
   + the ad's **style contract** → `{register (NATURAL|HYPED|CALM), persona_sentence (verbatim
   contract), hook_pattern (H1..H8), story_shape (S1..S19), n_shots, runtime plan}`. The style's
   register wins the persona tier; duration target → shot count via the H3 grid.
2. **Monologue pass** (`prompts.monologue_prompt`): writes the spoken lines with the anti-slop rules
   (density budget per shot, first-word constraint, banned openers/words, one peak per clip,
   performed dialogue). Returns `shots[]` with dialogue beats.
3. **Shot pass chain** (mirror of `_SCENE_PASSES`, trimmed for short form):
   `blocking → camera → action → references → dialogue`. Later passes merge only their fields.
   Per-shot schema: `{id, duration_s (H3 grid), continuous (bool), camera, action,
   dialogue:[{line, on_camera}], staging, soundscape, music}` — `staging` carries product-visible
   beats and the hand/angle rules.
4. **Review loop** (`studio/review.py`): *hook/slop reviewer* (banned openers/words, first-word rule,
   claim-without-concrete), *story reviewer* (one "but then" twist, product enters at 40–60%, CTA
   inside the closer, no outro beat), *runtime/format reviewer* (duration targets, ≥70% spoken).
   Failing script → revision up to `max_revisions`.
5. Stored as `script.json`; approve / reject.

**A3 — Storyboard** (`studio/storyboard.py`)
- Per-shot keyframes via Krea 2, **photoreal UGC direction** (from `rules/visual.md`) **plus the
  ad's style contract** (its `visual_look` / `lighting` / `color_grade` / `camera_texture` /
  `setting_defaults` / `wardrobe_anchor` are injected verbatim): iPhone-photo realism (23 mm wide
  look, deep focus, pore-level skin, mild digital noise; no beauty filter, no bokeh, no cinematic
  grade), consistent setting/lighting across the ad, creator identical to `creator/ref.png`.
- Product staging injected (from `rules/product.md` + `rules/performance.md`): angle lock, realistic
  hand-relative scale, exactly one hero product, clean placement, no legible text on props, safe
  interaction verbs, hand allocation, and — between *consecutive shots* — the anti-morph rule
  (adjacent shots must differ in POV + distance + action; no two adjacent shots share both).
- **Consistency QC** (vision LLM, mirror of the reference): per keyframe verify creator identity,
  product angle/label, hand count, no baked text; on failure rewrite the keyframe prompt and
  regenerate up to N rounds.

**A4 — Video + stitch** (`studio/render.py`, `studio/h3.py`, `studio/compile/shot_prompt.py`)
- Per shot: upload `[creator, product, keyframe]` as `ref_image_N` (order matches `<Picture N>`);
  the creator voice as `ref_audio_1`; build the H3 `ref2va` workflow at the shot's snapped duration
  (9:16).
- **Deterministic shot prompt compiler** emits the six-section MiniMax notation (`<Subject 1>` =
  creator, dialogue in `<d>[English] …</d>`), with the ad's **style contract** folded into
  `detailed_description` (look/lighting/grade/camera texture) and the **style's music_feel** into
  `non_diegetic_music`. No LLM in this path (optional LLM rewriter behind a config flag).
- **1-second previews** per shot (same workflow) for cheap QC.
- **Stitch orchestrator** (§8): shot 1 renders fresh; shots 2..N render as H3 retake extensions of
  the previous stitched video when `continuous=true`; otherwise ffmpeg hard-cut concat.
- **Frozen-frame QC** on the assembled video (mirror of the ugc-flow QA): one hero product, ≤2 hands,
  label not gibberish/reversed/other-brand, product scale vs hand, creator identity, no baked text;
  failures re-roll that shot and re-stitch.

---

## 7. Prompt architecture — "the core handles the detailed prompting"

The system ships **rule packs** (static markdown under `studio/rules/`, like the ugc-flow
`references/*.md`), loaded and injected by the prompt builders. The LLM only makes high-level
creative decisions; every technical / visual / video detail is rule-injected or compiled
deterministically. The rule packs are the *only* place the anime project's domain could leak — they
are written fresh, photoreal, UGC-specific:

```
studio/rules/
  style.md          # per-ad style catalog + contract shape (visual_look, lighting, color_grade,
                    #   camera_texture, setting_defaults, wardrobe_anchor, music_feel, register)
  monologue.md      # density budgets, first-word rule, banned openers/words, performed dialogue,
                    #   at-most-one-peak; S1..S19 story shapes; H1..H8 hook patterns;
                    #   NATURAL/HYPED/CALM persona tiers (persona sentence = verbatim contract)
  product.md        # staging contract: description rules, angle lock, realistic scale,
                    #   exactly-one-hero, placement, absent-feature negatives, label/wordmark,
                    #   safe interaction verbs, mechanism anatomy, one state per prop
  performance.md    # hand allocation (2 hands / 1 role), selfie vs static POV, distance bands,
                    #   anti-morph across adjacent shots, micro-behaviour menu, body-event peak
  visual.md         # photoreal UGC realism: iPhone-photo look, lighting, setting continuity,
                    #   no-bake-text, no real brands, no mirrors/reflections, NO anime style
  keyframe.md       # per-shot keyframe prompt rules (Krea 2) built from product+performance
  miniMax.md        # six-section notation contract + <Subject>/<Picture>/<Audio>/<d> grammar
```

Prompt builders (`studio/prompts.py`) inject the relevant packs verbatim and demand strict JSON. The
compiled H3 prompt (`compile/shot_prompt.py`) is deterministic.

**Verbatim contracts** (from the ugc-flow): `persona_sentence`, register, `hook_pattern`,
`story_shape`, the canonical `product_description`, the brand's approved claims, and the ad's
**`style_contract`** are decided once and **restated verbatim** in the monologue, every keyframe,
and every video prompt — nothing downstream paraphrases or drifts.

---

## 8. Video generation + H3 stitch specifics

- **Workflow**: `build_h3_ref2va_workflow` ported verbatim (refs as sockets → `<Picture N>` /
  `<Audio N>`); 9:16 canvas (e.g. 768×1344) from config; sampling per `config/comfy.yaml`.
- **Durations**: snapped to the H3 grid (`compile/durations.py`); ad target 15–60 s → 2–5 shots.
- **Stitch orchestrator** (`studio/stitch.py`, new):
  - Shot 1: fresh `ref2va` render (creator + product + keyframe refs, voice as `<Audio 1>`).
  - Shot k>1, `continuous=true`: `build_h3_retake_workflow` (ported) with
    `base_video = previous stitched MP4` (via `ComfyClient.upload_video`),
    `retakeStart = current end frame`, `retakeLength = shot k frames`,     `retakePrompt = shot k's MiniMax prompt`, `global_prompt = the ad-level continuity prompt`
    (setting, lighting, style contract, creator, product state). Result replaces the running video.
  - Shot k>1, `continuous=false`: render fresh, splice with **ffmpeg hard-cut concat** (no
    transitions) at the boundary timestamp.
  - Resumable per shot; preview + final QC run on the assembled result.
- **GPU management**: port the reference GPU manager (exclusive COMFYUI ownership; serialize Krea 2
  vs H3); per-shot `free_memory()`.

---

## 9. Dashboard & approval gates (`studio/dashboard.py` + `dashboard.html`)

All UX is dashboard-only. Navigation:

- **Ad Groups** — list / create / open.
- **Group** tabs: Brand · Product (upload + normalization preview + approve/reject/re-normalize) ·
  Creator (photo upload or generate, ref + voice preview, per-asset approve/reject).
- **Ads** — list; create ad (direction + duration + **style preset or free-form style**) ; open an ad.
- **Ad** tabs: Overview (brief + style contract + direction + duration) · Script (register/hook/story
  summary + full shot table: dialogue, camera, action, staging, duration, continuous flag;
  approve/reject with notes) · Storyboard (keyframe contact sheet + consistency verdicts, per-shot
  reject→regenerate) · Video (previews, render + stitch progress, frozen-frame QC report, assembled
  player, re-roll shot).
- Live activity/progress panel + background job model (port of the reference dashboard).

Approval modes per gate (`config/approval.yaml`: `gated | auto`) so an ad can run hands-free between
the gates the user cares about.

---

## 10. Configuration & project layout

```
MarketingStudio/
  pyproject.toml
  studio.py                     # entrypoint -> dashboard (and dev CLI)
  studio/
    config.py                   # ported loader (sections: llm, comfy, pipeline, approval, review, env)
    adgroup.py                  # Ad Group data model (identity container)
    ad.py                       # Ad data model (per-ad run state)
    intake.py                   # G1 product intake + normalize
    creator.py                  # G2 creator + voice
    scriptgen.py                # A2 monologue + review loop
    prompts.py                  # prompt builders (inject rules/, strict JSON)
    storyboard.py               # A3 keyframes + consistency QC
    render.py                   # A4 H3 ref2va per shot
    stitch.py                   # A4 H3 Retake Stitch orchestrator + ffmpeg concat
    review.py                   # UGC reviewers
    approval.py                 # gate state machine
    dashboard.py / dashboard.html
    gpu_manager.py              # ported
    h3.py                       # ported ref2va + retake-stitch builders
    compile/ {durations.py, shot_prompt.py}
    clients/ {lmstudio.py, comfy.py, tts.py, ffmpeg.py}
    rules/ {style.md, monologue.md, product.md, performance.md, visual.md, keyframe.md, miniMax.md}
  config/
    llm.yaml comfy.yaml pipeline.yaml approval.yaml review.yaml env.yaml
  workflows/image_keyframe.json  # ported Krea 2 graph
  ad_groups/                     # per-group state (identity once, ads many)
```

Ported 1:1 plumbing from `anime/`: `config.py`, `clients/{lmstudio,comfy,tts,ffmpeg}.py`,
`gpu_manager.py`, `h3.py` (ref2va + retake builders), `compile/durations.py`,
`workflows/image_keyframe.json`, and the dashboard/review/approval patterns. Written fresh with UGC
semantics: `adgroup.py`, `ad.py`, `intake.py`, `creator.py`, `scriptgen.py`, `prompts.py`,
`storyboard.py`, `render.py`, `stitch.py`, `rules/*`. **No anime prompts, config keys, or style
references are copied.**

---

## 11. Out of scope / future work

- Caption burn stage (timing from the final audio transcript).
- Post package (caption, hashtags, pinned comment) as dashboard text.
- Product URL intake; creator voice cloning from a 5–10 s upload.
- Local talking-head model swap behind a config switch on the render driver.
- Multi-ad batch rendering across an ad group's GPU budget.
