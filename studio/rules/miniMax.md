# MiniMax H3 prompt grammar (Full-Reference Mode)

The compiled H3 prompt is DETERMINISTIC (compile/shot_prompt.py); this file is
the contract it implements. Six sections, in order:

```
subject_definitions:
<Subject 1> is <creator name>, shown in <Picture 1>, <appearance>.
<Audio 1> is the voice-timbre reference for <Subject 1> (S1).

summary:
[reference generation + audio reference] <ad summary>

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - <name>'s identity, face, hair, body and appearance are retained exactly as shown.
<Audio 1>: reference - its vocal timbre guides the dialogue delivery of <Subject 1> without copying the original signal.

detailed_description:
<style line>
[Shot 1] <Subject 1> (<name>), <appearance>. <action>. <camera>. <product staging>. <Subject 1> (S1) says, using the voice timbre referenced from <Audio 1>, <d>[English] <line></d>

overall_soundscape:
<shot soundscape or N/A>

non_diegetic_music:
<style music_feel or shot music or N/A>
```

## Rules

- `<Subject N>` is the reusable identity (the creator); `<Picture N>` is the raw
  reference frame it comes from (Picture 1 = creator, then product / keyframe as
  composition anchors, referenced only for composition, never as a subject).
- `<Audio N>` binds the creator voice sample; dialogue is spoken ONLY inside
  `<d>[English] exact words.</d>`.
- The style line folds in the ad's style contract (`visual_look`, `lighting`,
  `color_grade`, `camera_texture`).
- The product staging text must follow product.md (angle lock, scale, one hero,
  mechanism).
- Soundscape and music are the last two sections; `N/A` when absent.
- No `@voice` or audio-reference notes inside the prompt string — audio is
  attached as a generation reference, never described.
