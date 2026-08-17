# Visual realism rules (photoreal UGC)

Every keyframe and every video prompt follows these rules. This is the hard
anti-anime guarantee: all output is photoreal UGC — never anime, never 2D,
never stylized.

## Photoreal iPhone-photo realism

- Natural light (inherited from the style contract; default soft daylight).
- Slight phone-camera grain, deep focus — background stays sharp.
- Pore-level skin realism — vellus hair, natural texture, asymmetric moles; no
  smoothing, no glow, no beauty filter.
- Mild HDR flattening, slight highlight clipping at windows, faint digital noise
  in shadows (digital noise, never film grain).
- One motivated light source (window / lamp / daylight), consistent white
  balance.
- NO shallow depth of field, NO bokeh, NO lens flares, NO cinematic color grade,
  NO studio lighting, NO glossy retouching — unless the style contract
  explicitly asks (UGC that looks like cinema reads as an ad).
- iPhone front-camera optics: 23mm-equivalent wide look, mild wide distortion at
  frame edges (never fisheye, never ultra-wide warp).
- NO anime, NO 2D, NO illustration, NO stylized lineart, NO "cinematic anime
  keyframe" language.

## No baked text

- No on-image text, no captions, no subtitles, no watermarks, no badges, no
  numbers, no pop-text on any keyframe or video generation. Text is a post-render
  burn only.
- The product's own label (with a real photo) keeps its real text as part of the
  physical product — that is not added typography.

## Setting & continuity

- Same setting, time of day, and light direction across all shots of an ad
  unless the story crosses to a new location (then that change is itself a shot
  with `continuous=false`).
- Creator identity, outfit, and wardrobe anchor stay identical across shots —
  outfit may change only when the story explicitly transitions context.

## Banned

- Mirrors / reflection shots (mirrors spawn extra hands and duplicated bodies).
- Any other brand's logos or IP; real brands beyond the product's own label.
- Deformed hands; third arms; extra limbs; duplicated people.
- Text overlays of any kind baked into a generation.
