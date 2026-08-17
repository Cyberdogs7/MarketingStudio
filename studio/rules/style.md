# Per-ad style contract

Style is a property of the **ad**, not the group. The creator identity, product,
voice, and brand claims stay locked at the group; the style is free to vary per
ad. Every ad resolves its style ONCE into a single structured contract that is
restated verbatim at every downstream stage (monologue, keyframes, video, stitch,
review).

## Contract shape

```json
{
  "name": "Gritty Handheld Vlog",
  "register": "NATURAL",
  "visual_look": "raw handheld vlog",
  "lighting": "single warm practical lamp, high shadows",
  "color_grade": "muted, low-contrast, slight desat",
  "camera_texture": "mild handheld shake, iPhone grain, deep focus",
  "setting_defaults": ["bedroom", "desk", "bathroom"],
  "wardrobe_anchor": "oversized hoodie, no logos",
  "music_feel": "low lo-fi bed, drops out under the line"
}
```

`register` is one of NATURAL | HYPED | CALM and drives the persona tier +
monologue energy. `visual_look` / `lighting` / `color_grade` / `camera_texture`
inject into every keyframe prompt and the video prompt's style line. `music_feel`
feeds the video prompt's non_diegetic_music.

## Preset catalog

- **Authentic Bathroom GRWM** — NATURAL; bright bathroom vanity light; clean
  slightly-warm grade; steady front-facing static, deep focus; setting: bathroom;
  wardrobe: towel robe / bare shoulders; music: soft pop bed.
- **Clean Minimal Tech** — NATURAL; even flat daylight; neutral low-grade, high
  contrast edges; steady static close-ups on the product; setting: tidy desk;
  wardrobe: plain tee, no logos; music: minimal ambient.
- **Warm Morning Lifestyle** — NATURAL; golden morning window light; warm bright
  grade; gentle handheld, deep focus; setting: kitchen / living room; wardrobe:
  relaxed knitwear; music: acoustic bed.
- **Gritty Handheld Vlog** — NATURAL; single warm practical lamp, high shadows;
  muted desat grade; mild handheld shake, iPhone grain; setting: bedroom / desk;
  wardrobe: oversized hoodie; music: low lo-fi bed.
- **Calm Luxury Aesthetic** — CALM; soft diffused daylight; desaturated premium
  grade; slow deliberate camera, no shake; setting: minimal bedroom; wardrobe:
  silk / neutral tailoring; music: quiet ambient.
- **Bright Studio Product** — NATURAL; clean two-light softbox; bright even
  grade; steady static, product-forward framing; setting: plain studio backdrop;
  wardrobe: plain top; music: up-beat but subtle.

## Rules

1. A named preset expands to its contract. Free-form style direction is
   normalized by the LLM into the same contract shape — never invent fields.
2. The contract, once resolved, is a VERBATIM contract: never paraphrase it
   downstream, restate it exactly in every prompt that references style.
3. `register` always wins over a brief's implied energy when they conflict; a
   brief may request a different register explicitly, which re-resolves the
   contract before generation (never mid-run).
