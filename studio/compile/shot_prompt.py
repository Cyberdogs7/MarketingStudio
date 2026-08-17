"""Deterministic MiniMax H3 shot-prompt compiler (Full-Reference Mode).

Emits the six-section notation exactly per MiniMax's VIDEO_PROMPT_WRITING_GUIDE:

    subject_definitions
    summary
    retention_analysis
    detailed_description
    overall_soundscape
    non_diegetic_music

Rules followed verbatim:
- ``<Subject N>`` is a reusable identity; ``<Picture N>`` is the raw reference
  frame it comes from. ``<Subject 1> is <name>, shown in <Picture 1>, <appearance>.``
- ``<Audio 1>`` binds to its speaker's timbre.
- ``summary`` starts with ``[reference generation + audio reference]``.
- ``retention_analysis`` preserves the subject's identity exactly.
- ``detailed_description`` opens with the style line, then ``[Shot 1]`` with the
  speaker as ``<Subject 1> (S1)`` and dialogue ONLY inside ``<d>[English] ...</d>``.
- ``overall_soundscape`` / ``non_diegetic_music`` last; N/A when absent.

The ad's style contract is folded into the style line (look/lighting/grade/camera
texture) and its ``music_feel`` into non_diegetic_music. No LLM in this path.
"""
from __future__ import annotations

from typing import Any


def _first_lower(text: str) -> str:
    text = (text or "").strip()
    return text[:1].lower() + text[1:] if text else text


def _style_line(style: dict[str, Any] | None) -> str:
    if not style:
        return ("The target video is a photoreal UGC iPhone-style short: natural "
                "light, deep focus, real skin texture, no cinematic grading.")
    parts = [p for p in (
        style.get("visual_look"),
        style.get("lighting"),
        style.get("color_grade"),
        style.get("camera_texture"),
    ) if p]
    base = ("Photoreal UGC short. The target video uses this style contract: "
            + ("; ".join(parts) if parts else "natural iPhone look."))
    return base


def compile_shot_prompt(
    *,
    shot: dict[str, Any],
    creator: dict[str, Any],
    product_description: str,
    style: dict[str, Any] | None,
    ad_summary: str,
    n_pictures: int,
    audio_ref: bool = True,
) -> str:
    """Compile the six-section prompt for one H3 shot.

    ``n_pictures`` is the number of reference images uploaded (Picture 1 =
    creator; any further pictures are composition anchors such as the product).
    ``creator`` carries ``name`` + ``appearance_canonical``; ``shot`` carries
    ``action``, ``camera``, ``dialogue`` [{line, on_camera}], ``soundscape``,
    ``music``.
    """
    name = (creator.get("name") or "the creator").strip()
    appearance = (creator.get("appearance_canonical") or "").strip()

    # --- subject_definitions ---
    subj = "<Subject 1>"
    pic = "<Picture 1>"
    app_txt = _first_lower(appearance) if appearance else ""
    subject_lines = [f"{subj} is {name}, shown in {pic}"
                     + (f", {app_txt}" if app_txt else "") + "."]
    if audio_ref and n_pictures > 0:
        subject_lines.append(f"<Audio 1> is the voice-timbre reference for {subj} (S1).")

    # --- summary ---
    global_desc = (ad_summary or shot.get("summary") or "").strip()[:300]
    task = "[reference generation" + (" + audio reference" if audio_ref else "") + "]"
    summary_txt = f"{task} {global_desc or 'One short UGC ad shot.'}"

    # --- retention_analysis ---
    retention_lines = [
        f"{subj} (appears in [Shot 1]): fully_preserved - {name}'s identity, "
        f"face, hair, body and appearance are retained exactly as shown."
    ]
    if audio_ref:
        retention_lines.append(
            "<Audio 1>: reference - its vocal timbre guides the dialogue delivery "
            f"of {subj} without copying the original signal.")

    # --- detailed_description ---
    placed = [f"{subj} ({name})" + (f", {app_txt}" if app_txt else "")]
    parts: list[str] = []
    action = (shot.get("action") or "").strip()
    cam = (shot.get("camera") or "").strip()
    if action:
        parts.append(action)
    if cam:
        parts.append(cam)
    if product_description.strip():
        parts.append(f"Hold/present the product: {product_description.strip()[:400]}.")
    for d in (shot.get("dialogue") or []):
        line = (d.get("line") or "").strip()
        if not line:
            continue
        if audio_ref:
            parts.append(f"{subj} (S1) says, using the voice timbre referenced "
                         f"from <Audio 1>, <d>[English] {line}</d>")
        else:
            parts.append(f"{subj} (S1) says, <d>[English] {line}</d>")
    shot_txt = " ".join(p for p in parts if p)
    style_txt = _style_line(style)
    detailed = f"{style_txt}\n[Shot 1] {', '.join(placed)}. {shot_txt}".strip()

    # --- overall_soundscape / non_diegetic_music ---
    soundscape = (shot.get("soundscape") or "").strip()
    music = (shot.get("music") or "").strip() or (style or {}).get("music_feel", "")

    sections = [
        "subject_definitions:\n" + "\n".join(subject_lines),
        f"summary:\n{summary_txt}",
        "retention_analysis:\n" + "\n".join(retention_lines),
        f"detailed_description:\n{detailed}",
        f"overall_soundscape:\n{soundscape or 'N/A'}",
        f"non_diegetic_music:\n{music or 'N/A'}",
    ]
    return "\n\n".join(sections).strip()


def compile_stitch_global_prompt(
    *,
    ad_summary: str,
    style: dict[str, Any] | None,
    product_description: str,
    creator: dict[str, Any] | None = None,
) -> str:
    """Ad-level continuity prompt used as the retake workflow's global_prompt.

    Keeps setting, lighting, style, product state and creator identity constant
    while shots are appended via H3 Retake Stitch.
    """
    style_txt = _style_line(style)
    creator_txt = ""
    if creator and (creator.get("appearance_canonical") or "").strip():
        creator_txt = (" The creator looks exactly as in the reference: "
                       + creator["appearance_canonical"].strip())
    prod_txt = (f" The product: {product_description.strip()[:400]}." if product_description.strip() else "")
    return (f"{style_txt}. Overall scene intent: {ad_summary or 'A short UGC ad.'}"
            + creator_txt + prod_txt)
