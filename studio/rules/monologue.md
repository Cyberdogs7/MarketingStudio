# Monologue craft — what the creator actually says

The monologue writer decides: register, persona sentence, hook pattern, story
shape, and the spoken lines split into shots. Word-density budget applies per
shot (a shot is one H3 clip, 4-15 s). Greetings and product introduction happen
ONLY in shot 1; later shots continue mid-thought.

## Word density per shot (seconds -> words)

| Shot length | Words |
|---|---|
| 4-10 s | 12-20 |
| 11-12 s | 20-28 |
| 13-15 s | 28-35 |

## Register tiers (one per ad, from the style contract)

- **NATURAL (default):** warm, genuine, engaged creator. Lively and real; ONE
  honest human-scale peak (a real grin, a delighted "oh"). Never squealing or
  screaming. The persona sentence carries NO energy words.
- **HYPED (only on explicit hype signal):** 2000s It-Girl / Hype Beast / Drama
  Queen energy, big reactions.
- **CALM (only on explicit calm signal):** deadpan / quiet / refined delivery.

The **persona sentence** is written once and restated verbatim in every prompt
(character prompt, every keyframe, every video prompt). Example: "a warm,
girl-next-door creator, easy-going and dry-witty, genuinely delighted by good
products."

## Story mode is the default

One story spans the whole ad. Human stakes first (pain, embarrassment, money, a
ruined plan); the product enters as a SUPPORTING ACTOR at 40-60% of total
runtime; the CTA rides INSIDE the closer's resolution, never as an outro beat.
Pick ONE story spine:

S1 Accidental Find · S2 After-First Loop (open on result, rewind) · S3 Wrong Turn
(bought for X, used for Y) · S4 Witness (the skeptic converts on camera) ·
S5 Confession · S6 Interrupted Storytime · S7 GRWM With Stakes · S8 New-Place
Mini-Vlog · S9 Day-in-the-Life With a Twist · S10 Caved-In Unboxing ·
S11 POV Frame · S12 Process Win · S13 Reply-to-Comment · S14 Green-Screen
Commentary · S15 Rating Ritual · S16 Street Ask · S17 Fail-First · S18 Silent Flex
· S19 ASMR

Every story carries EXACTLY ONE "but then" twist (the mid-arc peak). No twist =
flat anecdote; two twists don't fit a short.

## Hook-pattern menu (the opener, ONE per ad)

- **H1 Impact Action** — frame one is physical mid-peak (box mid-rip, product
  mid-catch); the first word lands during the action.
- **H2 Mid-Sentence Confession** — opens on word four of a sentence.
- **H3 Pattern Interrupt** — a normal setting with one deeply wrong thing,
  delivered with total normalcy.
- **H4 Freeze-Reaction** — the face already in full reaction; a performed hold,
  THEN the first line.
- **H5 Hostile Open** — the first line challenges the viewer.
- **H6 Quirk-First** — the quirk IS the first event (only when opted in).
- **H7 Result-First** — the outcome visibly on screen, unexplained; the first
  line refers backwards.
- **H8 Fake Stitch** — slot one is repost-texture product footage; hard cut into
  the creator mid-reaction.

## Anti-slop pass on every line

- The first words are NEVER: `Okay wait / Okay so / OMG / Hey guys / So basically
  / Stop scrolling / You NEED this / Story time`.
- Banned anywhere: "literally", "obsessed", "game-changer", "holy grail",
  "changed my life", "hits different", and corporate words (elevate / seamless /
  effortless).
- Friction openers beat enthusiasm ("I almost returned this.").
- Every claim carries one concrete — a number, a time, a named comparison.
  Praise without a concrete gets cut. When the group's brand has an
  approved-claims list, use ONLY those exact strings.
- At most ONE peak reaction per shot.
- **First-word constraint (every shot's segment):** the literal FIRST WORD must
  be hook content — never `OK / Okay / Alright / So / Yeah / Um / Well / Like /
  Wait / Hold on`.

## Performed dialogue (emotion lives IN the words)

The video model under-renders flat prose. Use: vowel-stretch on the peak word
("it's SO good"), 1-2 CAPS volume spikes per line max, one broken sentence at the
peak ("it's— okay wait. LOOK."), a flat -> spike -> settle arc across the clip.
Under NATURAL the peak stays human-scale (a real gasp, a breaking grin), never
staged screaming. Never write engineered pauses — they bloat the line.

## Audio state is explicit per shot (anti-gibberish)

H3 renders video and audio jointly. If the compiled video prompt never states
whether the creator speaks, the model invents vocal noise (gibberish mumbling)
to fill the audio track. Every shot therefore declares its audio state EXPLICITLY:

- **SPEAKING shot** — `dialogue` has one or more spoken lines. Each line is
  written verbatim (the exact words, no descriptions). `on_camera: true` = the
  creator is on screen and her lips move in sync with the line; `on_camera:
  false` = an off-camera voiceover running over the visual (her lips stay
  closed), used only when a line must continue over a beat where the creator is
  not shown speaking.
- **SILENT shot** — `dialogue` is `[]` (empty). This is the EXPLICIT declaration
  that the creator says nothing in this shot: reaction beats, product close-ups,
  setting / transition / insert shots. Never write a line for a purely visual
  beat, and never imply speech where there is none.

Rules:

- Dialogue lives ONLY in `dialogue[]`. The camera / action / sound passes never
  add spoken words, and the soundscape never repeats them.
- A shot is speaking OR silent — no third state, no ambiguity. A silent shot is
  a deliberate choice, not a gap.
- Across the ad ~70% of runtime is still spoken (per the density table), but
  individual shots may be fully silent when the beat is visual.
- The sound pass fills a silent shot's audio layer with room tone / environment
  so the audio is intentional, not empty.

## Product claims

Use ONLY the brand's approved claims, each as its exact verbatim string. Never
paraphrase, strengthen, combine, or derive a new claim. No approved list = no
numeric or comparative claims go into speech.
