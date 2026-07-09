# Aether Studio — Professional Production Spec: Stages 0–2 (RECOVERED ORIGINAL)

> Recovered 2026-07-09 from Amir's copy of the original pipeline spec (pre
> Windows-reinstall). Preserved verbatim as the authoritative reference for
> stages 0–2. The merged, buildable contract (with Amir's v2 changes: krea2
> primary image model, automation-first) lives in
> `anime-pipeline-v2-design.md`.

## Models Reference

| Task | Model | Parameters | Context |
|---|---|---|---|
| All script/screenplay LLM work | qwen3:8b | think:false, keep_alive=300 (stages 0-2) | 16384 tokens |
| Panel vision analysis | qwen2.5vl:7b | think:false, keep_alive=0 | 4096 tokens |
| Image generation (primary) | z-anime-distill-4step-fp8 | 4 steps, euler sampler, fp8 quant | 832×1216px |
| Image generation (fallback) | flux1-schnell-Q4_K_S.gguf | disabled by default, only after 5 z-anime failures | 832×1216px |
| Animation | Wan2.2-TI2V-5B fp8 KJ build | 20 steps, unipc, block-swap=20, cfg=5.0 | 81 frames @ 16fps |
| TTS | Kokoro in-process | CUDA, loaded once, reused all shots | — |

**Temperature guide across all LLM calls:**
- 0.1 = extraction and analysis (must be precise, no creativity)
- 0.2 = conservative synthesis (grouping, classifying, ordering)
- 0.3 = structured creative work (blueprint outlines, shot plans)
- 0.4 = dialogue (character voice consistency matters)
- 0.5 = creative expansion and world-building depth
- 0.6 = narration rewrites (targeted creative variation)

---

## STAGE 0 — SCRIPT

### Stage 0B — GENERATE (Original from Brief)

Three-pass pipeline. qwen3:8b for all three.

#### Pass 1 — Story Blueprint

Purpose: Commit to structure before writing prose. The LLM cannot invent the
ending while writing the opening if it doesn't know what the ending is.

Input data:
- User's creative brief: genre, tone, power system description, protagonist
  archetype, themes, specific requests, episode length (word target)
- World bible context: all existing characters (name, role, arc_notes from
  previous episodes), active story hooks (unresolved threads from
  episode_log), world rules

LLM call parameters: Temperature 0.3, Format JSON, Max tokens 2000.

Output JSON structure:

```jsonc
{
  "title": "episode title",
  "logline": "protagonist + concrete goal + specific obstacle + stakes if they fail",
  "characters": [
    {
      "name": "character name",
      "role": "protagonist/antagonist/mentor/ally/obstacle/neutral",
      "personality_core": "3 specific traits — not generic (not brave/smart) but specific (reckless-when-protecting-others, reads-people-too-accurately-for-comfort, performs-calm-while-calculating-escape)",
      "episode_want": "what they are explicitly trying to achieve this episode",
      "episode_fear": "what they are trying to avoid this episode",
      "episode_arc_end": "where they are emotionally/situationally by episode end — must be different from start",
      "new_or_recurring": "new | recurring",
      "if_recurring_existing_id": "character id from world bible"
    }
  ],
  "three_act_structure": {
    "act1": {
      "scenes": ["scene 1 title", "scene 2 title"],
      "inciting_incident": "the specific event that forces the protagonist into action — not vague",
      "establishes": "what the audience learns about the world and stakes in Act 1"
    },
    "act2": {
      "scenes": ["scene 3 title", "scene 4 title", "scene 5 title"],
      "escalation": "how the conflict gets worse — specific events, not 'things escalate'",
      "midpoint_reversal": "the specific belief the protagonist held that is proven wrong at the midpoint",
      "what_breaks": "what resource, relationship, or ability the protagonist loses or has taken in Act 2"
    },
    "act3": {
      "scenes": ["scene 6 title"],
      "climax_decision": "the specific choice the protagonist must make — with both options named",
      "cost": "what the protagonist loses or sacrifices regardless of which choice they make",
      "permanent_change": "what is different about the world or protagonist after this episode that cannot be undone"
    }
  },
  "scene_list": [
    {
      "number": 1,
      "title": "evocative scene title — not 'scene 1' or 'opening'",
      "act": 1,
      "location": "specific location name",
      "characters_present": ["name1", "name2"],
      "emotional_purpose": "what the audience should feel and understand after this scene",
      "narrative_function": "what story information this scene delivers"
    }
  ],
  "thematic_core": {
    "surface": "what the plot is about",
    "deeper": "what the story is really about beneath the surface",
    "moral_question": "the specific moral dilemma the episode puts to the audience"
  }
}
```

Character count: No cap. If the brief calls for 3 characters, 3 are in the
list. If the world bible has 8 recurring characters relevant to this episode,
all 8 are listed. Each recurring character references their world bible ID.

**Human touchpoint — Blueprint Review screen:**
- Logline displayed prominently for quick "does this feel right" check
- Character list with edit buttons (rename, change role, adjust arc_end)
- Three-act structure shown as a horizontal timeline
- Scene list as draggable cards (reorder, add, remove)
- Approve button → advances to Pass 2
- Reject + brief notes → re-runs Pass 1 with notes appended to brief
- Edit individual fields inline without re-running

#### Pass 2 — Scene-by-Scene Prose

Purpose: Each scene written with full context window attention on that scene
alone. One LLM call per scene prevents quality degradation that happens in
long single-pass generation.

Input data (per call):
- This scene's entry from the approved blueprint (title, act, location,
  characters present, emotional purpose, narrative function)
- The full three-act structure summary (so the writer knows where this scene
  sits in the whole)
- Character profiles for characters present in this scene: name, speech
  style, personality core, episode want, episode fear, previous arc notes
- Location description (from world bible if location exists, or invented
  fresh with description to be added to world bible)
- Word target for this scene (calculated: total_word_target / scene_count,
  adjusted +30% for climax, -20% for transitional scenes)

LLM call parameters: Temperature 0.5, raw text (not JSON), max 1500 tokens
per scene.

Output: prose scene with scene title marker at top; narrative prose in
present tense, third-person limited; character dialogue in quotation marks,
attributed; clear scene-ending beat (the state that changed).

Word count enforcement: After generation, count words. If >130% of target:
ask for the scene condensed to essential beats only. If <70% of target: ask
for the scene expanded with more character interiority and sensory detail.
Both are separate LLM calls using the original scene as input.

Per-scene quality check (automated, no LLM):
- Opens with action or dialogue (not environment description) — check first 20 words
- Contains at least one line of dialogue — count quote marks
- Ends differently from opening state — checked heuristically (first vs. last
  50 words character/mood)
- If any check fails: the check name and the scene are flagged for user
  attention. User can accept as-is or trigger a rewrite for that scene only.

#### Pass 3 — Integration

No LLM call. All scene prose assembled in blueprint scene order with scene
break markers: `--- [SCENE 1: Scene Title] ---`

Automated validation:
- Total word count vs. target: reported as percentage
- All character names from blueprint found in prose: check each name
- All location names from blueprint found in prose: check each name
- No scene exceeds 30% of total word count

Result is saved as script.txt. Stage 0B complete.

### Stage 0A — TRANSFORM (Source → Original)

Four-pass pipeline. qwen3:8b for all passes.

#### Pass 1 — Mechanics Extraction

Input: Source text (first 4000 characters — mechanics appear in the setup,
not the full story). Temperature 0.1, JSON.

Extraction target — structural mechanics only, never plot or characters:

```jsonc
{
  "power_system_type": "what category (cultivation/LitRPG stats/magic system/ability-based/etc)",
  "power_mechanics": ["each specific rule of how the power works — be precise"],
  "progression_model": "how characters grow stronger (training/leveling/awakening/consumption/etc)",
  "conflict_engine": "one of: zero-sum-competition / betrayal-from-within / external-invasion / internal-corruption / knowledge-vs-power / identity-dissolution",
  "conflict_specifics": "what makes this particular conflict work in this story — not the characters, the structural tension",
  "protagonist_archetype": "one of: reluctant-hero / amoral-genius / underdog-overcomer / broken-redeemer / outsider-observer / chosen-by-circumstance",
  "protagonist_behavioral_pattern": "how the protagonist specifically responds to problems — their decision-making pattern",
  "emotional_hooks": ["specific emotional pull the story uses to keep readers invested — be concrete"],
  "world_rules": ["internal logic rules that make the setting feel consistent"],
  "themes": ["idea or question the story explores"],
  "what_makes_it_original": "what genuinely distinguishes this from generic examples of the genre"
}
```

#### Pass 2 — Originality Design

Input: Mechanics JSON from Pass 1. Temperature 0.5, JSON.

Purpose: Design all original equivalents before writing any prose. The
transformation map is a contract: every element from the source gets a new
version.

```jsonc
{
  "world_design": {
    "name": "new world name — not a translation or obvious reference to source",
    "geography": "what the world looks like physically — climate, terrain, scale",
    "cultural_flavor": "what cultural aesthetic this world draws from — be specific",
    "visual_signature": "the one visual element that makes this world instantly distinctive",
    "what_is_scarce": "what resource or power or condition is rare and therefore valuable"
  },
  "power_system_original": {
    "name": "the new name for this power system",
    "source_mechanic_used": "which mechanic from the original is being adapted",
    "new_skin": "how the mechanic is implemented differently — specific differences",
    "new_rules": ["rules that are specific to this version, not in the source"],
    "visual_manifestation": "what it looks like when this power is used — the distinct visual signature"
  },
  "character_originals": [
    {
      "source_archetype": "which protagonist_archetype from Pass 1 this maps to",
      "new_name": "invented name appropriate to the world's cultural flavor",
      "new_personality": "how this archetype is expressed differently — what makes them distinct from the source character",
      "new_history": "completely different backstory that serves the same narrative function",
      "new_relationship_network": "who they are connected to and how — entirely original"
    }
  ],
  "conflict_redesign": {
    "source_engine_used": "which conflict_engine from Pass 1 is being adapted",
    "new_factions": ["who the new opposing forces are — original names and nature"],
    "new_stakes": "what specifically is at risk in this version — different from source",
    "new_inciting_event": "what triggers the conflict in this version"
  },
  "original_commentary_layer": {
    "angle": "what thematic angle this original version adds that the source doesn't have",
    "how_it_manifests": "specific plot or character choices that express this angle"
  }
}
```

**Legal proximity score (computed after Pass 2):**
- Character archetype match: −10 per archetype that maps 1-to-1 with no differentiation
- Conflict engine match: −20 if conflict engine is identical with no new factions/stakes
- Power mechanic match: −15 per mechanic copied without modification
- World rule match: −10 per rule that is identical
- Score starts at 100. Below 75: warning shown, user can proceed or refine.
  Below 50: block — requires user acknowledgment and modification before Pass 3.

**Human touchpoint — Transformation Map Review:** source mechanics on the
left, original designs on the right, every field editable, legal score shown
prominently. Approve → Pass 3. Refine → specific fields re-run.

#### Pass 3 — Blueprint
Same as Stage 0B Pass 1, using the transformation map and original character
designs as input instead of a free brief.

#### Pass 4 — Scene Prose
Same as Stage 0B Pass 2, using the transformation map and original world
design as world context.

### Stage 0I — IMPORT (Existing Panels → Story)

Four-pass pipeline. qwen2.5vl:7b for vision (Pass 2), qwen3:8b for everything else.

#### Pass 1 — Panel Inventory

No LLM. Pure file system operations.
- Check file extension (PNG, JPG, WEBP accepted)
- Check file size: <5KB = flagged as likely blank/corrupted
- Sort by filename using natural sort (panel_001, panel_002 — NOT
  alphabetical sort that gives panel_1, panel_10, panel_2)
- If zip uploaded: extract to temp dir, then process
- Panel classification: landscape panels = likely covers/horizontal; file
  size >3× median = likely full-page splash

Output shown to user before any vision call (totals, flagged files,
full-page panels, processing order) with Proceed / Skip flagged / Re-upload.

**Panel limit: 60 panels maximum per import.** Above 60 the synthesis call
exceeds safe context length. If upload has >60: user chooses first 60, last
60, or manual range.

#### Pass 2 — Per-Panel Vision Analysis

Model qwen2.5vl:7b. One call per panel. Sequential (not parallel — 8 GB VRAM).

Per-panel JSON: characters (exact hair/eyes/skin/build/clothing/
distinguishing feature, position_in_frame, specific expression), action
(start state → end state), dialogue (speaker description, exact bubble text,
bubble type), mood (tense|peaceful|dramatic|action|emotional|mysterious|
triumphant|ominous), setting (interior/exterior/abstract, description, time
of day), shot_type (wide|medium|close_up|detail|action), panel_notes.

Failure handling:
- Tier 1 — partial JSON: accept, missing fields null.
- Tier 2 — parse failure: regex-extract `{...}`; else minimal entry with
  `manual review required` note.
- Tier 3 — call failed: log, include as Tier 2 minimal entry.
- All Tier 2/3 panels listed for the user at end of pass.

Progress: "Analyzing panel 12/42..." with thumbnail in UI.

#### Pass 3 — Character Identity Resolution

Model qwen3:8b, temperature 0.2. **The most important missing step** — same
person described differently across panels must not create duplicate world
bible entries.

- Step A: build appearance fingerprints (hair, eyes, clothing color, build)
- Step B: LLM clusters descriptions into unique individuals, flags uncertain
  groupings

Output: characters with provisional_id, canonical_appearance,
appears_in_panels, speaks_in_panels, confidence, uncertainty_notes; plus
uncertain_groupings with provisional assignment.

**Human touchpoint — Character Identity screen:** cluster cards with
thumbnails, name input ("Give this character a name"), merge/split controls,
confirm/deny uncertain groupings. Names become character_id downstream;
dialogue re-attributed via provisional_id → real_name.

#### Pass 4 — Screenplay Synthesis

qwen3:8b, temperature 0.2, JSON. Every panel = exactly one shot. Scenes =
consecutive panels with the same setting (3-8 panels typical).

Per shot: shot_id, scene_id, shot_type, description (start→end state),
narration (1-2 sentences adding what the panel doesn't show), dialogue
(resolved character ids + exact text), sd_prompt, source_panel.

- Panel coverage check: every panel in exactly one shot; missing patched as
  minimal shots; duplicates flagged.
- Narration quality filter: same banned-pattern filter as Stage 2.
- Output: screenplay JSON + script.txt summary + fair-use score displayed.

---

## STAGE 1 — WORLD BIBLE

Model qwen3:8b all steps, keep_alive=300.

### Step 1 — Full-Script Character Scan

Fixes truncation: chunks of 8000 characters with 400-char overlap; per-chunk
temperature 0.1 JSON call: "List every character name mentioned…including
shortened names and titles". Merged + case-insensitively deduplicated. No cap.

### Step 2 — Per-Character Profile Extraction

One call per character, temperature 0.1. System gathers every
sentence mentioning the character (plus pronoun follow-ups in-paragraph) into
a 200-800 word context block. Recurring characters extend (not overwrite)
their existing entry.

Output schema (key fields): id (stable snake_case), name, aliases,
appearance {hair, eyes, skin, build, clothing_primary,
distinguishing_feature — all exact, thumbnail-recognizable}, **sd_prompt
(40-60 words, appearance only, no camera/scene/lighting)**,
voice_id_suggestion (from the Kokoro list below), speech_style {category,
avg_words_per_line bucket, vocabulary_register, distinctive_patterns},
personality {5 behavioral-pattern traits, core_drive, core_fear}, role,
arc_this_episode {starts, ends}, first_episode.

**Voice ID assignment logic:**
- Male + formal/deep → am_eric, am_onyx
- Male + young/energetic → am_adam, am_puck
- Male + villain/grave → am_michael, am_fenrir
- Female + protagonist/warm → af_heart, af_nova
- Female + cool/analytical → af_jessica, af_kore
- Female + narrator-style → af_bella, af_nicole
- British male → bm_george, bm_lewis; British female → bf_emma, bf_isabella
- LLM suggests; user can override in world bible editor.

### Step 3 — World and Lore Extraction

One call (chunked like Step 1), temperature 0.1, JSON. Locations (id, name,
description, mood, lighting, time_associations, 40-60-word sd_prompt with no
characters/camera), power_system (name, how_it_works, requirements, costs,
failure_modes, forbidden_applications, progression), world_rules,
lore_entries, and new_contradictions [{new_claim, existing_claim, location}].

### Step 4 — Contradiction Detection and Deduplication

Automated (no LLM): exact ID match, exact name match, alias↔name matches →
merge. Fuzzy match (LLM temp 0.1) for the rest → same/different/uncertain;
uncertain → user decision.

Merge logic: keep existing ID (past episodes reference it); add new aliases;
arc_notes appended chronologically; appearance/sd_prompt keep existing unless
empty.

Contradiction UX (blocking until resolved/dismissed):
`[Accept new] [Keep existing] [Mark both valid: different factions believe
different things] [Custom resolution note]`

### Step 5 — Creative Expansion

One call, temperature 0.5, JSON on the cleaned world bible:
- character_depths: hidden_motivation, wound, secret, series_arc_potential,
  relationship_tensions [{with_character_id, tension_type, what each wants
  from the other, what prevents it}]
- world_history: ancient / recent (5-20 yrs, caused current conflict) /
  ongoing crisis
- factions: name, goal, methods, public_face, hidden_nature,
  relation_to_protagonist
- story_hooks: hook, type (mystery/promised-confrontation/unrevealed-identity/
  hidden-agenda/ticking-clock), payoff_type, urgency (low-burn/medium/high)
- thematic_core: surface_theme, deeper_theme, recurring_motifs, moral_question

---

## STAGE 2 — SCREENPLAY

Model qwen3:8b, keep_alive=300.

### Step 1 — Shot Plan Generation

Temperature 0.15, JSON. Input: complete world bible + full script (chunked).
Output: title, logline, act_breakdown, scenes [{scene_id, number, act,
evocative title, location_id, characters_present, mood, thematic_purpose,
emotional_arc, shots [{shot_id, number, shot_type, description
(action-not-state), emotional_beat, characters_in_frame}]}].

Shot count rules (automated post-check): no two consecutive shots same
shot_type; each scene has ≥1 differing shot_type; climax scene has the most
shots; warn if total <20 or >60.

### Step 2 — SD Prompt Assembly

**No LLM call. Pure data assembly.** Priority order:
1. Character appearance anchors (highest): world-bible sd_prompt — fixed
   string, identical every time. Max 2 characters per shot; 3+ in frame →
   only the 2 most narratively important.
2. Location anchor: scene's location sd_prompt, trimmed to 40 words.
3. Shot composition: description stripped to visual-only terms (no camera
   words, no emotion words).

Composition rules: 120-word budget (characters ~50, location ~30,
composition ~30, style ~10). Style tail always added: *"anime 2d
illustration, manga panel style, high quality linework, cel shading"*.
Overflow: trim composition first, then location, **never** character
anchors. No character names, no camera-angle words in the prompt.

### Step 3 — Narration Craft

One call for all narration, temperature 0.5, JSON. Six techniques rotated
across the episode (not resetting per scene): interiority →
stakes/consequence → world/history → irony/reversal → foreshadowing →
sensory detail → repeat.

Exception rules: action shots always get stakes/consequence or foreshadowing;
climax shots always irony/reversal or foreshadowing; first shot of each scene
always world/history or stakes/consequence.

**Banned pattern regex filter (post-generation, automated):**
```
\b(he|she|they|\w+) is not just\b
truth is (a |an )?(blade|fire|sword|weapon|mirror|shield)
past is (a |an )?(storm|mirror|shadow|ghost|wound|memory)
world hums with
\bthe (weight|burden|cost) of (destiny|power|fate|legacy|sacrifice|choice)\b
\b(he|she|they) (stand|stands) alone\b
```
On match → rewrite queue: single-shot call, temperature 0.6, with failed
narration + description + emotional beat + technique. Re-filtered; if it
fails again → narration = "" (silence preferred over bad narration).

### Step 4 — Dialogue Craft

One call for all dialogue, temperature 0.4, JSON. Input includes each
character's full speech_style + personality + scene wants/fears. Output per
shot: dialogue [{character_id, line, optional delivery_note (whispered/
shouted/trailing off/cutting in)}].

Speech style validation (automated): clipped characters (<8 avg words) with
a >20-word line → flagged; verbose characters (>20 avg) with a <6-word line
→ flagged. Summary shown; user edits or ignores.

Dialogue deduplication (automated): same first 60 characters as any earlier
line → flagged for review.

### Step 5 — Narration Quality Audit

One call, temperature 0.3, JSON. Identifies: 3 weakest narration lines
(most abstract/vague/generic) with improved replacements; adjacent-shot
technique conflicts with suggested changes; >2-sentence narrations with
trims. All fixes applied automatically, re-run through the banned-pattern
filter; failures surface for manual edit. Cost ~10 s.

---

## Stage Connection Summary

```
Stage 0 → script.txt  (three modes: 0B Generate / 0A Transform / 0I Import)
Stage 1 → full-script character scan → per-character profiles →
          world/lore extraction → contradiction+dedup → creative expansion
          → world_bible.json (sd_prompt anchors)
Stage 2 → shot plan → SD prompt assembly (no LLM) → narration craft →
          dialogue craft → quality audit → screenplay.json
Stage 3B → one image per shot (anchored prompts = consistency)
Stage 4 → Kokoro TTS narration + per-character dialogue
Stage 5 → ffmpeg assembly → final MP4
```

## Priority Implementation Order (original)

1. SD prompt assembly from world bible anchors (Stage 2 Step 2) — biggest visual quality gain
2. Fix Stage 2 import mode block — unblocks import pipeline
3. Narration rewrite instead of silent drop — prevents silent shots
4. Narration quality audit pass — cheapest per-shot quality improvement
5. Full-script character scan with chunking (Stage 1 Step 1) — no characters missed
6. Per-character extraction with full context (Stage 1 Step 2) — deeper profiles
7. Contradiction detection with user resolution (Stage 1 Step 4) — continuity
8. Character deduplication with fuzzy matching (Stage 1 Step 4) — world bible cleanliness
9. Character identity resolution in import mode (Stage 0I Pass 3) — prevents world bible splitting
10. Stage 0 Generate 3-pass restructure — script structural quality
11. Stage 0 Transform originality design + legal score — legal safety
12. Per-shot motion effect control UI — user experience
13. Portrait generation button in world bible — character tooling
14. Subtitle generation in Stage 5 — accessibility
15. Config: comfyui_install_path from .env — maintenance
