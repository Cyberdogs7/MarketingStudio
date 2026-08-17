# PROMPTING — Image & Audio Reference Workflow

How H3 shot prompts are built when a shot carries **image references** (`<Picture N>`)
and **audio references** (`<Audio N>`). This is the `ref2va` ("reference-to-video")
path that gives the studio character identity and voice-timbre consistency per shot.

Authoritative code:
- `studio/render.py` — `compile_shot_prompt()` builds the prompt (six sections).
- `studio/h3.py` — `build_h3_ref2va_workflow()` wires refs as sockets on `MiniMaxH3ReferenceToVideo`.
- `studio/prompts.py` — `monologue_prompt()` / shot passes (LM Studio LLM context).
- `studio/compile/shot_prompt.py` — the deterministic compiler (dialogue + silence grammar).

Prompting sources this guide is distilled from:
- MiniMax H3 Ref2VA rewrite guide: `skills/h3-prompt-writing/references/ref-en.txt` and
  `base-en.txt` in <https://github.com/MiniMax-AI/MiniMax-H3> (speaker `(Sx)` IDs, `<d>[Language] …</d>`,
  voiceover lips-closed rule, `N/A` = explicit silence).
- Luma MiniMax H3 prompting guide: <https://lumalabs.ai/learning-center/articles/minimax-h3-prompting-guide>
  (dialogue as part of the performance; separate dialogue / ambience / SFX / music).
- Community cheat sheet: <https://www.reddit.com/r/StableDiffusion/comments/1vnis23/>
  ("dialogue needs a visible speaker … explicitly say who does not speak too" — the anti-gibberish rule).

---

## 1. What the workflow is

One shot = one H3 generation. The shot's refs are uploaded to ComfyUI and connected
to the node's `ref_image_0..8` / `ref_audio_0..2` sockets **in connection order**.
The node auto-labels them `<Picture 1>…<Picture 9>` and `<Audio 1>…<Audio 3>` in that
same order, and the prompt references those tags directly. There is no other link
between the prompt and the actual refs — get the order or the tags wrong and H3
uses the wrong face or wrong voice.

Two kinds of reference:

| Kind | Tag | Feeds from | Limit |
|---|---|---|---|
| Image ref | `<Picture N>` | character refs, object refs, storyboard keyframe | ≤ 9 total |
| Audio ref | `<Audio N>` | per-character voice samples (raw wav) | ≤ 3 |

Plus the derived identity tag:

| Tag | Meaning |
|---|---|
| `<Subject N>` | the reusable person/identity. Bound to its `<Picture N>` in `subject_definitions`. Every appearance of a character in dialogue/action uses `<Subject N>`, never a bare name. |
| `(Sx)` | speaker index **within the shot**, from dialogue order — first speaking line is `S1`. |

---

## 2. Reference ordering (critical)

The pipeline builds the image list in a fixed order (`render.py:_render_shot`):

1. **Character refs first**, one per on-screen character, in the order returned by
   `_shot_refs()` (`studio/storyboard.py:106`). This is the identity anchor — its
   `<Picture N>` number **must** match the `names` order used to compile `<Subject N>`.
2. **Object refs** (recurring props matched from the shot's action text, `_shot_object_refs()`).
3. **The shot's storyboard keyframe** (`runs/EP##/storyboard/<sid>.png`) last — it is
   the composition anchor, not an identity anchor.

Rule of thumb: **who goes in `<Subject N>` goes first.** If a character ref is missing
or fails to upload, the pipeline skips it rather than reordering the rest, so the
`<Picture N>` numbers still line up with `names`. Never hand-edit the order or you
will decouple subjects from their pictures.

Audio refs are appended **after** all image refs, one raw voice sample per speaking
character, in dialogue order, up to 3. Audio refs are only attached when the shot
also has image refs (the model requires them together).

---

## 3. Image references

### Character refs (identity)
Generated once at bootstrap under reference-sheet discipline
(`studio/bootstrap.py:300`):

> `Anime character reference portrait of {name}. {appearance_canonical}. Full body,
> front view, neutral standing pose, plain studio background, clean lineart,
> consistent character design, high quality.` — aspect 3:4.

Deliberately staged: neutral pose, plain background, minimal accessories. That makes
the identity conditioning strong, so the ref stays reusable across every shot and
costume. Approved refs live in `shows/<id>/characters/<cid>/refs/`; the first
approved image is the one H3 uses (`_shot_character_ref`, `render.py:63`).

- **Use the base ref for identity.** Costume changes are declared per shot via
  `references.costumes`; the wardrobe pass keeps the ref list stable so a costume
  swap never changes `<Picture N>` numbering.
- **One ref per character.** A character in the ref list with no uploaded ref simply
  doesn't appear as a subject — check the render log if a character is missing.

### Object refs (recurring props)
Slug-matched from capitalized multi-word phrases in the shot's action/camera text
against `runs/EP##/objects/<slug>.png` (`_shot_object_refs`). Camera phrases are
excluded. Objects pull lightly — they guide the prop, never the character.

### Storyboard keyframe (composition)
Every shot's first-frame storyboard still is appended as the final image ref. It
anchors composition/pose; identity still comes from the character refs ahead of it.

---

## 4. Audio references

- Source: the **approved voice sample** for each speaking character,
  `assets/voice/<cid>_voice.wav` (`_voice_sample_path`, `render.py:85`).
- Uploaded **raw as-is — no conversion** (the proven example workflow does the same).
- Attached per speaking character in dialogue order; **max 3 audio refs per shot**.
- Only characters who both (a) speak in the shot **and** (b) are in `names` get an
  audio ref.

The audio ref is a **voice-timbre** reference, not a line read. H3 keeps the character's
vocal quality but speaks the lines written in the `<d>` tokens. The prompt states this
explicitly in both `subject_definitions` and `retention_analysis` (below).

> Because H3 renders video and audio jointly, the audio ref conditions the video too —
> this is what produces **in-model lip-sync** for on-camera speakers.

---

## 5. Prompt anatomy — the six sections

`compile_shot_prompt()` emits exactly six sections, in this order, per MiniMax's
`VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`. When a section has no content it is `N/A`,
never omitted. Tags (`<Picture N>`, `<Audio N>`, `<Subject N>`) are used verbatim.

### 5.1 `subject_definitions`
Define every reusable identity, then bind each audio ref to its speaker:

```
<Subject 1> is Kiyo, shown in <Picture 1>, mid-20s woman, silver bob cut...
<Audio 1> is the voice-timbre reference for <Subject 1> (S1).
```

- Appearance comes from the character's `appearance_canonical`, lowercased first
  letter, trailing period stripped.
- The `(S1)` here is the shot-local speaker id (first line spoken → `S1`).

### 5.2 `summary`
One line starting with the task-type prefix — the prefix changes with what refs exist:

```
[reference generation + audio reference] Kiyo gets the package on the rooftop.
```

| Refs present | Prefix |
|---|---|
| images only | `[reference generation] …` |
| images + audio | `[reference generation + audio reference] …` |

The body is the script/scene summary, capped at 300 chars.

### 5.3 `retention_analysis`
Confirms what is preserved, one line per subject and per audio ref:

```
<Subject 1> (appears in [Shot 1]): fully_preserved - Kiyo's identity, clothing and appearance are retained exactly as shown.
<Audio 1>: reference - its vocal timbre guides the dialogue delivery of <Subject 1> without copying the original signal.
```

Note: the audio line carries **no `(Sx)`** here — the `(Sx)` appears only in
`subject_definitions` and `detailed_description`.

### 5.4 `detailed_description`
Style opening line, then the shot beat:

```
{style_guide}
[Shot 1] <Subject 1> (Kiyo), mid-20s woman, silver bob cut. Kiyo lands on the rooftop,
looks over the district. wide establishing, slow push-in. <Subject 1> (S1) says, using
the voice timbre referenced from <Audio 1>, <d>[English] The package. Where is it?</d>
```

- Composition: `action` then `camera`, joined.
- **Every spoken line lives inside `<d>[English] …</d>`.** Never put dialogue words
  outside the token — H3 reads bare words as narration.

#### Dialogue and silence are explicit (anti-gibberish)

H3 generates the audio track jointly with the video. A shot prompt that shows the
creator but never states whether they speak makes H3 invent **gibberish mumbling**
to fill the audio. Every shot therefore carries an explicit vocal clause — either
a speaking clause or a silence clause, never neither. This follows MiniMax's own
`VIDEO_PROMPT_WRITING_GUIDE` / Ref2VA guide (speakers get `(Sx)`; voices that
never vocalize are explicitly silent; voiceover lines end with the speaker's lips
closed) and the community cheat-sheet rule ("explicitly say who does not speak").

| Shot type | Template |
|---|---|
| speaking, on-camera + audio ref | `<Subject N> (Sx) says, using the voice timbre referenced from <Audio N>, <d>[English] line</d>` |
| speaking, on-camera, no audio ref | `<Subject N> (Sx) says, <d>[English] line</d>` |
| speaking, off-camera voiceover | `<Subject N> (Sx) says in an off-screen voiceover, <d>[English] line</d>, while <name>'s lips remain completely closed` |
| speaking — closure after the last line | `<name> stops speaking and remains silent, lips closed, for the rest of the shot.` |
| **silent shot** (no dialogue) | `<Subject N> does not speak in this shot - <name> remains completely silent, lips closed, no dialogue.` |

- `on_camera: false` (voiceover) is used only when a line must continue over a beat
  where the creator is not shown speaking; the **lips-closed note is mandatory** so
  H3 does not sync mouth movement to a line it cannot see spoken.
- A silent shot keeps `<d>` out of the prompt entirely and states the silence
  outright; its audio layer is then filled by `overall_soundscape` (room
  tone / environment). `overall_soundscape: N/A` means intentional total silence.
- Dialogue is never repeated in `overall_soundscape` / `non_diegetic_music`.

### 5.5 `overall_soundscape`
Environment/Foley, e.g. `wind, distant sirens`. `N/A` when absent.

### 5.6 `non_diegetic_music`
Music cue, e.g. `bass drone`. `N/A` when absent.

---

## 6. The optional LLM rewrite pass

When `pipeline.h3_rewrite_prompt` is enabled (`render.py:292`), the deterministic
prompt above is handed to a local LLM (`h3_rewrite_prompt`, `prompts.py:1542`) which
expands it into a rich 250–500 word production brief. Its hard constraints:

- **Keep every reference tag verbatim** — `<Picture N>`, `<Audio N>`, `<Subject N>`
  unchanged.
- **Keep the exact dialogue words** — only re-wrap/expand around them.
- Dialogue stays inside `<d>[English] …</d>`, bound to the speaking character's tag.
- Returns plain text; on any failure the deterministic prompt is used unchanged.

The LLM runs GGUF/NF4 off the primary GPU so it does not compete with the H3 render
for VRAM. Its job is enrichment (composition, lighting, camera, motion, placement) —
never re-numbering or re-voicing.

---

## 7. The deterministic multi-shot compiler (other path)

`compile_h3_prompt()` (`studio/compile/h3_prompt.py`) is the non-ref path for
prompting a full timeline (t2v/`fl2va`). Reference-relevant differences:

- `subject_definitions:` is a single space-joined line, not per-line.
- `retention_analysis:` is generic: `Keep the identity, face and clothing of
  <Subject 1> and <Subject 2> consistent across every shot.`
- Shots are numbered `[Shot N]`, later shots carry strictly increasing
  `At MM:SS.mmm` cut timestamps computed from cumulative durations.
- Dialogue in list form emits `<Subject N> speaks, <d>[English] line</d>`.

`render.py` does **not** use this path for reference shots — the Full-Reference
six-section form in §5 is what ships to `ref2va`. Keep the two forms straight: the
six-section form for ref2va shots, the timeline form for fl2va/keyframe batches.

---

## 8. Rules checklist

- [ ] Character refs are the first image refs; their order matches `names`/`<Subject N>`.
- [ ] ≤ 9 image refs, ≤ 3 audio refs, ≤ 3 speaking characters with audio.
- [ ] Audio refs only on shots that also have image refs.
- [ ] Voice samples uploaded raw (no conversion).
- [ ] `subject_definitions` binds every `<Subject N>` to its `<Picture N>`.
- [ ] `summary` prefix matches the ref set: `[reference generation + audio reference]`.
- [ ] `retention_analysis` audio lines have **no** `(Sx)`.
- [ ] **Every shot declares its vocal state explicitly**: spoken lines inside
      `<d>[English] …</d>` bound to `<Subject N> (Sx)` and, when present,
      `referenced from <Audio N>`; **or** an explicit silence clause
      (`does not speak … remains completely silent, lips closed`). Never neither.
- [ ] Off-camera voiceover lines carry the lips-closed note; speaking shots close
      the lips after the last line.
- [ ] `overall_soundscape` / `non_diegetic_music` = `N/A` when empty (never omitted);
      `N/A` soundscape = intentional total silence.
- [ ] LLM rewrite preserves tags verbatim and dialogue words exactly, or is dropped.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Character has the wrong face | `<Picture N>` / `names` order mismatch; ref missing/upload failed | Re-check `_shot_refs` order; confirm the ref file exists and `refs.json` status is `real` |
| Character doesn't appear at all | Character not in `references.characters`; no approved ref | Fix the shot's cast; approve/regenerate the ref image |
| Wrong vocal timbre or no lip-sync | Audio ref missing/not attached | Speaker must be in `names`, have a voice sample, and the shot must have image refs |
| Bare words spoken as narration | Dialogue outside `<d>` tokens | Re-wrap lines inside `<d>[English] …</d>` |
| **Gibberish audio / mumbling when the creator shouldn't speak** | The shot's prompt never states the creator's vocal state, so H3 invents speech to fill the audio | Ensure the shot has an explicit clause: spoken lines inside `<d>` **or** `… does not speak in this shot - … remains completely silent, lips closed, no dialogue.` |
| Creator keeps mumbling after a line | No mouth-closure after the dialogue | Append `… stops speaking and remains silent, lips closed, for the rest of the shot.` after the last `<d>` line |
| Mouth moves but no line is heard (voiceover) | On-camera form used for an off-screen line | Use `says in an off-screen voiceover, <d>…</d>, while <name>'s lips remain completely closed` |
| Missing subject/audio in output | Rewriter dropped a tag | Disable `pipeline.h3_rewrite_prompt` or tighten the rewrite system prompt |
| Ref rejected by renderer | File too large / bad format | Re-export the wav/png; keep refs at H3-native sizes |
