# Keyframe prompt rules (Krea 2, per shot)

Each shot's keyframe is a single photoreal UGC still that anchors the H3 clip's
composition and identity. Built deterministically by the storyboard stage; no LLM
in this path. The prompt must include, in order:

1. **Identity anchor** — the creator appears EXACTLY as in the creator reference
   image: same face, hair, body, skin tone. Never describe or alter their
   appearance.
2. **Style contract (verbatim)** — the ad's `visual_look`, `lighting`,
   `color_grade`, `camera_texture`, `setting_defaults`, `wardrobe_anchor` from
   the style contract, restated exactly.
3. **Shot staging** — this shot's POV (selfie/static), distance band
   (TIGHT/MID/WIDE), camera framing, and physical action, plus the hand
   allocation (each hand's single role, idle hand parked).
4. **Product staging (if visible)** — angle lock (only the front-facing side
   from the product photo), realistic hand-relative scale, exactly one hero
   product, clean placement, mechanism anatomy, absent-feature negatives.
5. **Micro-behaviour** — the performance beat for this shot (from the
   performance rules), ONE peak per ad.
6. **Realism tail** — the visual.md realism rules: photoreal UGC, iPhone-photo
   look, no beauty filter, no bokeh, no cinematic grade, NO anime, no text, no
   watermark.

For multi-shot ads, the keyframe for shot k>1 must also preserve the setting,
lighting, wardrobe, and product state established in shot k-1 (no re-closed cap,
no new outfit) so the shots read as one continuous take.

Render at 9:16 via the Krea 2 keyframe workflow with the creator ref (and product
ref when the product is visible) as IPAdapter references.
