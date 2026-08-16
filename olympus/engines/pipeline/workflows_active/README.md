# Active Pipeline Workflows (Organized by Stage)

This folder contains only the ComfyUI workflows actively used by the Anime Pipeline v2.
The original `workflows/` folder contains deprecated/experimental files; this is the curated set.

## Structure

```
workflows_active/
├── manifest.json                  # Patchable key map for all templates
├── master_pipeline_graph.json     # Combined stage3b + stage3c visual graph
├── pipeline_full_graph.json       # End-to-end visual graph (plate → panel → LTX → video)
├── stage1r/                       # Stage 1R: Reference Images (after world bible)
│   ├── character_turnaround_sheet.json   # Character turnarounds (Flux, VRAM-efficient)
│   └── mouth_viseme_sheet.json           # Viseme frames for lip-sync (inpainting)
├── stage3b/                       # Stage 3B: Panels (after screenplay)
│   ├── image_krea2_txt2img.json                # Krea2 txt2img (plates, fallback)
│   ├── image_flux_fallback_txt2img.json        # Flux fallback (plates/panels)
│   ├── image_anima_txt2img.json                # Anima txt2img (plates)
│   ├── panel_krea2_img2img_plate.json          # Krea2 reference-first img2img (primary)
│   ├── panel_anima_img2img_plate.json          # Anima reference-first img2img (alt)
│   └── panel_krea2_ipadapter.json             # Krea2 IPAdapter identity/style (M-AP-7)
├── stage3c/                       # Stage 3C: Animation (after audio)
│   ├── video_ltx2b_i2v.json   # Primary: LTX-2 2B I2V (self-contained on 8GB)
│   ├── video_ltx23_i2v.json   # Fallback: LTX 2.3 22B tiled (tier-2/long frames)
│   ├── video_wan_i2v.json     # Wan 2.2 I2V 5B GGUF
│   ├── video_wan_t2v.json     # Wan 2.2 T2V 5B GGUF
│   └── video_hailuo_i2v.json  # Hailuo 2.3 I2V (MiniMax H3)
└── stage_lora/                   # LoRA Training Dataset Preparation (no ComfyUI trainer)
    ├── lora_caption_wd14.json          # WD14 tagger captioning for single image
    ├── lora_caption_qwen3.json         # Qwen3-VL natural-language captioning for single image
    ├── lora_dataset_batch.json         # Batch folder captioning: WD14 → save .txt per image
    └── lora_caption_qwen3_batch.json   # Batch folder captioning: Qwen3-VL → save .txt per image
```

## Naming Convention (2026-08-11)

Stage prefix + model + variant, all `snake_case.json`:

| Prefix | Meaning |
|--------|---------|
| `character_` | Stage 1R character reference |
| `mouth_` | Stage 1R lip-sync viseme |
| `image_` | Stage 3B standalone txt2img (plates, fallbacks) |
| `panel_` | Stage 3B panel composition (img2img, IPAdapter, txt2img) |
| `video_` | Stage 3C image/text-to-video |
| `lora_` | LoRA training dataset preparation |
| `master_` / `pipeline_` | Combined visual graphs for the UI Load menu |

## Pipeline Stage → Workflow Mapping

| Pipeline Stage | Workflow(s) Used | Router |
|----------------|------------------|--------|
| **stage1r** (refs) | `character_turnaround_sheet.json`, `mouth_viseme_sheet.json` | `image_router.pick_character_template()` |
| **stage3b** (plates) | `image_krea2_txt2img.json` / `image_anima_txt2img.json` / `image_flux_fallback_txt2img.json` | `image_router.pick_template(role="primary")` |
| **stage3b** (panels) | `panel_krea2_img2img_plate.json` / `panel_anima_img2img_plate.json` / `panel_krea2_ipadapter.json` / `image_flux_fallback_txt2img.json` | `image_router.pick_panel_template()` |
| **stage3c** (animation) | `video_ltx2b_i2v.json` / `video_ltx23_i2v.json` / `video_wan_i2v.json` / `video_wan_t2v.json` | `video_router.pick_ltx_template()` + Hailuo API |
| **lora** (dataset prep) | `lora_dataset_batch.json` / `lora_caption_qwen3_batch.json` | (manual, not part of the auto pipeline) |

## LoRA Training Workflows

LoRA **training** itself is not a ComfyUI stage — it runs via `pipeline/lora_docker.py`
which kicks off kohya-ss inside a podman container. The four `lora_*` workflows here
cover everything ComfyUI does well: dataset preparation.

- **`lora_caption_wd14.json`** — WD14 tagger on a single image (anime-friendly, fast).
  Only needs the `wd-v1-4-moat-tagger-v2` model in `ComfyUI/models/taggers/`.

- **`lora_caption_qwen3.json`** — Qwen3-VL natural-language captioning for one image.
  Better for character/location/style LoRAs where you want sentence captions.
  Requires a Qwen3-VL text encoder in `ComfyUI/models/text_encoders/`.

- **`lora_dataset_batch.json`** — Batch: read images from a directory, run WD14,
  save `.txt` caption files alongside the images. Uses VHS `LoadImagesFromDirectoryPath`.

- **`lora_caption_qwen3_batch.json`** — Same as above but with Qwen3-VL natural-language
  captions instead of WD14 tags.

Typical usage: prepare a folder of training images, run the batch workflow against it,
then pass the captioned dataset folder to `pipeline/lora_docker.py::train_lora_podman()`.

## Notes

- **Manifest**: `manifest.json` defines `patchable` keys for every template. The `ComfyClient` validates on load.
- **Routing**: No stage hardcodes template names. Routers check weight presence + smoke gates before selecting.
- **Banned models**: `manifest.json` lists banned checkpoints; `ComfyClient` refuses to queue them.
- **Original folder**: `../workflows/` retains all files (including deprecated SDXL templates, test workflows, krea2 LTX experiments) for reference.

## Two Format Versions

The pipeline workflows live in **API format** (flat dict keyed by node ID string):
```json
{"1": {"class_type": "KSampler", "inputs": {...}}, "2": {...}}
```
This is what ComfyUI's `/prompt` HTTP endpoint expects and what the pipeline code patches.

For viewing in ComfyUI's UI Load menu, the workflows must be in **UI format** with
`nodes` array, `links` array, `last_link_id`, and node positions:
```json
{"nodes": [...], "links": [...], "last_link_id": 39, "version": 0.4}
```

### Converting API → UI format

Run the converter script to generate UI-format copies for the ComfyUI graph:

```bash
# Single file
.venv/bin/python olympus/engines/pipeline/tools/api_to_ui_converter.py \
    olympus/engines/pipeline/workflows/panel_krea2_img2img_plate.json \
    ComfyUI/user/default/workflows/panel_krea2_img2img_plate.json

# All active workflows → ComfyUI workflows folder
.venv/bin/python olympus/engines/pipeline/tools/api_to_ui_converter.py --all \
    olympus/engines/pipeline/workflows_active/
```

The converter auto-positions nodes in a 4-column grid and builds the `links` array
from each node's input connections. Keep API-format files in `workflows/` for the
pipeline code; generate UI-format copies into `ComfyUI/user/default/workflows/`
for the graph view.

## Usage in Code

```python
from pipeline.comfy_client import ComfyClient, WorkflowTemplate

comfy = ComfyClient(config)
# Stage 1R
template = WorkflowTemplate.load("stage1r/character_turnaround_sheet.json")
# Stage 3B panels
template = WorkflowTemplate.load("stage3b/panel_krea2_img2img_plate.json")
# Stage 3C
template = WorkflowTemplate.load("stage3c/video_ltx2b_i2v.json")
```

The `WORKFLOWS_DIR` in `comfy_client.py` would need to point here for direct loading, or use the original `workflows/` folder (which the code currently uses).
