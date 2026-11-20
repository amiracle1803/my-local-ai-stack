# LTX anime video and Director integration

Updated: **2026-11-20**. This supersedes the earlier claim in this file that
LTX Director was the validated primary engine on the current installation.

## Current support matrix

| Engine | Local status | Use |
|---|---|---|
| `ltx2b` | **Installed and rendered locally** | Anime T2V and panel-guided I2V on the RTX 4070 Laptop 8 GB |
| `ltx_director` | **Experimental / blocked** | Text or image-directed timelines after its separate nodes and 22B models are installed |
| `svd_xt` | Installed fallback | Short image-driven clips without prompt control |

`stack.toml` currently selects `[animation] engine = "ltx2b"`. The working
renderer is `pipeline/ltx2b.py`; it uses the installed
`ltxv-2b-0.9.8-distilled-fp8.safetensors` and
`t5xxl_fp8_e4m3fn.safetensors`. No cloud generation is involved.

## LTX 2B anime T2V and I2V

The default stage3c path is I2V: the shot panel anchors the first frame and the
Director pass supplies its motion/camera beat. Set `OLYMPUS_LTX_MODE=t2v` to use
the shot's chronological `director.json` `t2v` paragraph without a panel. If
that field is absent, the shot remains I2V.

For both engines, `director.json` `seconds` controls the requested duration.
`ltx2b.frames_for()` rounds to the LTX `8n + 1` frame rule: 49 frames is about
2.04 seconds and 97 frames about 4.04 seconds at 24 fps.

`ltx2b.py` prepends an editable anime style and uses an anime/motion negative
prompt with occlusion/foreground-obstruction terms by default. Pass `style=""`
to opt out. Prompts work best when they put an unobstructed subject and concrete
action first, setting second, and camera last. The Director system prompt also
requires exact hair/clothing/colors to survive every composition rewrite. A
fixed-camera instruction is guidance, not a guarantee: the measured I2V clip
still changed framing.

### Reusable smoke command

```bash
PYTHONPATH=olympus/engines/pipeline .venv/bin/python \
  olympus/engines/pipeline/tools/ltx_anime_smoke.py \
  --engine ltx2b --mode t2v --seed 42 --seconds 4 \
  --output ~/Videos/ltx-director/anime_t2v.mp4
```

For I2V, add `--mode i2v --panel /path/to/panel.png`. The CLI also exposes
width, height, steps, and prompt. It writes an MP4 and a JSON metrics sidecar.
The Director option is available for a future compatible install but is not a
tested local option today.

## Importable ComfyUI workflow family

Three UI-format presets live in `olympus/engines/pipeline/workflows/ui/` and are
installed under ComfyUI `user/default/workflows/olympus/`:

| Preset | Default controls |
|---|---|
| `ltx2b_anime_t2v.json` | 768×512, 97 frames, 24 fps, 8 steps, fixed seed 42 |
| `ltx2b_anime_i2v.json` | Same sampling controls plus start panel and panel strength 1.0 |
| `ltx2b_anime_preview.json` | 512×320, 49 frames, 24 fps, 4 steps, fixed seed 42 |

They are derived from ComfyUI's official `ltxv_text_to_video` and
`ltxv_image_to_video` templates. Labelled nodes expose the local models,
positive/negative prompts, dimensions, frame count, fps, steps, seed/CFG, panel
strength, and MP4 output. Notes inside each graph explain the `8n + 1` rule and
action-first prompting. They contain no Director nodes.

Rebuild and reinstall them after changing the generator:

```bash
PYTHONPATH=olympus/engines/pipeline .venv/bin/python \
  olympus/engines/pipeline/tools/build_ltx_anime_workflows.py \
  --install --panel /path/to/start-panel.png
```

The install step copies the panel to ComfyUI `input/olympus_anime_start_panel.png`
for the ready-to-run I2V example. Replace it through **INPUT · start panel** for
other shots.

## Measured local results (2026-11-20)

All three production renders below are H.264, 768×512, 97 frames at 24 fps
(4.041667 seconds), eight steps, seed 42. Wall time includes model loading and
any ComfyUI queue wait.

| Output in `~/Videos/ltx-director/` | Wall time | Visual review |
|---|---:|---|
| `lanternfall_anime_t2v_seed42.mp4` | 30.06 s | Coherent anime and lantern tower, but Aya starts occluded and camera motion dominates |
| `lanternfall_anime_t2v_action_seed42.mp4` | 114.13 s | Action-first prompt keeps Aya visible from frame 0 and shows clearer climbing; simpler cel look |
| `lanternfall_anime_i2v_seed42.mp4` | 30.11 s | Strong panel/style/character continuity and visible climbing; framing drifts despite fixed-camera wording |

Matching `*_contact.png` sheets and JSON sidecars are saved beside the clips.
The actual UI fast-preview topology (`SamplerCustom` + `SaveVideo`) also ran
successfully: `lanternfall_anime_preset_preview_seed42.mp4` is H.264, 512×320,
49 frames at 24 fps (2.041667 seconds), four steps, seed 42, with 23.381 seconds
reported between ComfyUI execution start and success. Its contact sheet shows a
coherent but simpler low-resolution anime composition, as expected for preview
settings.

A real stage3c router integration run also passed using an isolated project. The
router received `panel=None`, honoured `seconds = 2`, returned one clip with zero
failures, marked blueprint stage3c done, and skipped rendering on the immediate
resume run. Mechanical success was followed by same-shot, same-seed visual
comparisons (49 frames, seed 3719193412):

| Canonical clip variant | Wall time | Visual decision |
|---|---:|---|
| `clip_cl01_v001` | 24.25 s | **Rejected:** tower/stairs occlude most of Aya despite the visibility prompt |
| `clip_cl02_v001` | 30.16 s | **Rejected:** occlusion and climbing improve, but identity/clothing regress after the composition-only rewrite |
| `clip_cl03_v001` | 24.18 s | **Usable integration baseline:** canonical hair/scarf/coat and unobstructed full-body visibility restored; climbing is subtler and lighting shifts toward daylight |

The forced cl02/cl03 renders retain cl01 for comparison. Each clip has an audit
JSON sidecar and a canonical `contact_cl0N_v001.png` sheet. This iteration added
occlusion terms to the shared LTX negative prompt and changed the Director system
prompt so future T2V paragraphs must retain exact identity and clothing together
with visible action and an unobstructed sightline.

## LTX Director timeline integration (not locally runnable yet)

`pipeline/ltx_director.py` loads the **API-format**
`workflows/ltx_director_23_extender.json` graph. Its per-shot timeline is now:

- I2V: `[{type: "image", imageFile: panel}, {type: "text", prompt: motion}]`
- T2V: `[{type: "text", prompt: chronological_action}]`

Both modes patch `local_prompts`, `segment_lengths`, `duration_frames`,
`duration_seconds`, width, height, global anime guidance, and seed together.
Graph construction and stage3c routing are unit-tested in both directions.
That is not evidence that the unavailable Director nodes can execute these
graphs.

The graph uses `LTXDirectorExtender` and `LTXDirectorGuideExtender`, a 22B LTX
2.3 GGUF, Gemma/text-projection encoders, the LTX 2.3 VAE, chunked FFN, tiled
VAE decode, and `VHS_VideoCombine`. The current ComfyUI server reports
`LTXDirector`, `LTXDirectorExtender`, `LTXDirectorGuide`, and
`LTXDirectorGuideExtender` as absent. Its 22B/Gemma/VAE model set is also absent;
only LTX 2B and T5 are installed. Therefore no real Director render or hardware
claim is made here. The supplied LTX 2.5 Director UI workflow likewise requires
an unavailable model generation and is not a drop-in validation route.

## Verification boundary

- **Verified:** LTX 2B T2V/I2V rendering, a real stage3c T2V run with resume,
  media validity, visual contact-sheet review, native preset node/model
  availability, preset installation, and Director graph/routing unit tests.
- **Not verified:** LTX Director execution, its 22B memory requirements on this
  host, true video-to-video segments, custom audio, and IC-LoRA guidance.
