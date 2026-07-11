# Per-Character LoRA Training Runbook (kohya sd-scripts)

Status: environment verified 2026-07-11 on Fedora Linux (flatpak sandbox host).
This unblocks WORK_QUEUE.md's "kohya train scripts fail argument parsing on
--help" item. **Read the "Known gap" section before running real training —
the CLI works, but there is an unresolved model-architecture mismatch that
blocks Stage 1R §2b from actually landing usable LoRAs today.**

## 0. Install location (already done, do not redo)

```
~/my-local-ai-stack/tools-external/sd-scripts/          # fresh clone, branch main, commit 0128ca0
~/my-local-ai-stack/tools-external/sd-scripts/.venv/     # uv venv, python 3.11.15
```

venv contents: `torch==2.6.0+cu124`, `torchvision==0.21.0+cu124`, plus
everything in `requirements.txt` (accelerate 1.6.0, transformers 4.54.1,
diffusers 0.32.1, bitsandbytes 0.49.2, safetensors, toml, etc.) and the
package itself (`-e .`, installed as `library==0.0.0`).

Verify anytime with:
```bash
cd ~/my-local-ai-stack/tools-external/sd-scripts
.venv/bin/python -c "import torch; print(torch.cuda.is_available())"   # -> True
.venv/bin/python sdxl_train_network.py --help                          # exit 0
```

There was **no actual bug** in sd-scripts' argument parsing. The WORK_QUEUE
"known issue" traced to the old `E:\AI\kohya_ss` Windows checkout/venv, which
this task did not reuse (fresh clone + fresh venv per instructions). `--help`
worked correctly on the very first run once torch + `requirements.txt` were
installed cleanly.

## 1. Known gap — read before training (do not skip)

The pipeline's adopted primary image model is **krea2 (`krea/Krea-2-Turbo`)**,
per `docs/planning/krea2-lab-report.md`. Its architecture is a **new,
non-SDXL, non-FLUX DiT** (`Krea2Transformer2DModel`, Qwen3-VL-4B text
encoder, Qwen-Image VAE — see that report §1). `sd-scripts` (this checkout,
main @ 0128ca0, 2026-07) has **no krea2 training entrypoint**. The closest
relatives it does support are:

- `sdxl_train_network.py` — SDXL UNet + dual CLIP. Produces an SDXL-format
  LoRA. **Will not load on krea2** (per krea2-lab-report.md: "the on-disk
  SDXL LoRAs won't load on it").
- `anima_train_network.py` — trains for the `circlestone-labs/Anima` model
  (Qwen3-0.6B text encoder + LLM adapter + Qwen-Image VAE, MiniTrainDIT DiT).
  Architecturally a *cousin* of krea2 (shares the Qwen-Image VAE) but **not
  the same model** — krea2 uses a 4B Qwen3-VL encoder and its own
  `Krea2Transformer2DModel`, not Anima's weights. A LoRA trained against
  Anima will not load on krea2 either.

**Net effect:** the per-character LoRA gate (design doc `anime-pipeline-v2-design.md`
§1R.2b / §3B.5, "Stage 3B refuses to start without them") cannot currently
produce a LoRA that actually applies to the adopted krea2 checkpoint. Two
additional blockers stack on top of the architecture gap:

1. **No non-banned SDXL base checkpoint is on disk.** The only two SDXL
   checkpoints found (`NoobAI-XL-v1.1.safetensors`, `wai-illustrious-v110.safetensors`,
   under `.../ComfyUI/models/checkpoints/`) are both on the WORK_QUEUE.md
   model ban list. `sdxl_train_network.py --pretrained_model_name_or_path`
   needs a real, non-banned SDXL 1.0 base to train against.
2. krea2 itself is distributed as a GGUF quant (Q4_K_S) for the 8 GB VRAM
   budget — GGUF is not something sd-scripts' LoRA trainers read or write
   from natively; even if an upstream krea2 trainer appears, it will likely
   want the full-precision `diffusers` weights (~26 GB) to train against,
   which does not fit this card without CPU offload during training too.

**Recommended next step (not done here, needs a decision from Amir):**
either (a) watch kohya-ss/sd-scripts and diffusers for native `krea2`/
`Krea2Transformer2DModel` LoRA support and revisit, or (b) pick a
non-banned SDXL checkpoint as an interim base so the mechanical LoRA
pipeline (dataset → caption → train → checkpoint file) can be validated
end-to-end now, with the understanding those LoRAs get retrained once a
krea2-native trainer exists, or (c) train against Anima directly if Anima
ever becomes usable in the ComfyUI pipeline (it is not currently — no Anima
node/checkpoint is wired into any template per `node-additions-plan.md`).
This runbook documents the mechanics with `sdxl_train_network.py` since
that is the concretely-working script; swap `--pretrained_model_name_or_path`
and the script name once a krea2-compatible path exists.

## 2. WD14 captioning (per-character dataset)

`sd-scripts` ships `finetune/tag_images_by_wd14_tagger.py` (verified working,
`--help` exits 0). It downloads a WD14 tagger model from Hugging Face on
first run (`--repo_id`, default SmilingWolf tagger) and writes one `.txt`
caption file per image next to it.

```bash
cd ~/my-local-ai-stack/tools-external/sd-scripts

.venv/bin/python finetune/tag_images_by_wd14_tagger.py \
  --batch_size 4 \
  --caption_extension .txt \
  --general_threshold 0.35 \
  --character_threshold 0.7 \
  --remove_underscore \
  --undesired_tags "" \
  "/path/to/ref-frames/<slug>/char-<id>/"
```

Notes:
- `--onnx` requires `onnxruntime` (CPU) or `onnxruntime-gpu` — neither is in
  `requirements.txt` (commented out). Without `--onnx` it falls back to the
  TF/torch path already satisfied by the venv above; add
  `uv pip install --python .venv/bin/python onnxruntime-gpu` only if you
  want the faster ONNX path.
- Equivalent alternative: ComfyUI's **ComfyUI-WD14-Tagger** node
  (`node-additions-plan.md` line 16: "installed 2026-07-09, CUDA ORT
  verified"), if you'd rather caption inside a ComfyUI workflow instead of
  the CLI. Same underlying WD14 model; output format differs slightly (node
  writes tags into the image workflow / can save `.txt` alongside the image
  depending on node config) — pick one path per dataset, don't mix.
- After tagging, manually add/verify the identity token (e.g. `char_<id>`)
  and outfit tokens at the front of each caption file so identity and
  clothing stay separable (design doc requirement, §1R.2b: "captioned with
  outfit tokens so identity and clothing stay separable").

## 3. Dataset config toml skeleton

One toml per character. Minor characters use the 10-frame ref set at
`resolution = 1024` (SDXL-native); mains use the 30-40 frame set. Adjust
`class_tokens`/caption behavior to your captioning approach — if WD14 already
wrote per-image `.txt` files, use a fine-tuning-style subset (`metadata_file`
or plain `image_dir` with sidecar captions), not DreamBooth `class_tokens`.

```toml
# char-<id>.toml
[general]
shuffle_caption = true
caption_extension = ".txt"
keep_tokens = 1

[[datasets]]
resolution = 1024
batch_size = 1
enable_bucket = true

  [[datasets.subsets]]
  image_dir = "/path/to/ref-frames/<slug>/char-<id>/"
  # captions are the WD14 .txt files sitting next to each image
  # first tag in each caption file should be the identity token, e.g. char_<id>
```

## 4. Training commands

Rank/step values per design doc §1R.2b: **rank 8 / ~800 steps** for
10-frame minor-character sets, **rank 16 / ~1500 steps** for 30-40-frame
main-character sets. `--max_train_steps` is used directly instead of
epochs so the step count is exact regardless of dataset size.

Output path per design doc §1R.2b:
`/run/media/amirel/Amir1tb SSD/AI/Models/loras/<slug>/char-<id>.safetensors`
— that `loras/` directory does not exist yet on disk; create the
per-slug subdirectory before the first run (`--output_dir` does not
auto-create parents reliably on all versions):

```bash
mkdir -p "/run/media/amirel/Amir1tb SSD/AI/Models/loras/<slug>"
```

### Minor character (rank 8, ~800 steps)

```bash
cd ~/my-local-ai-stack/tools-external/sd-scripts

.venv/bin/accelerate launch --num_cpu_threads_per_process 1 sdxl_train_network.py \
  --pretrained_model_name_or_path="<path to a non-banned SDXL 1.0 base checkpoint>" \
  --dataset_config="/path/to/char-<id>.toml" \
  --output_dir="/run/media/amirel/Amir1tb SSD/AI/Models/loras/<slug>" \
  --output_name="char-<id>" \
  --save_model_as=safetensors \
  --network_module=networks.lora \
  --network_dim=8 \
  --network_alpha=4 \
  --learning_rate=1e-4 \
  --unet_lr=1e-4 \
  --text_encoder_lr1=5e-6 \
  --text_encoder_lr2=5e-6 \
  --optimizer_type="AdamW8bit" \
  --lr_scheduler="cosine" \
  --max_train_steps=800 \
  --save_every_n_epochs=1 \
  --mixed_precision="fp16" \
  --gradient_checkpointing \
  --cache_latents \
  --cache_text_encoder_outputs \
  --xformers
```

### Main character (rank 16, ~1500 steps)

```bash
cd ~/my-local-ai-stack/tools-external/sd-scripts

.venv/bin/accelerate launch --num_cpu_threads_per_process 1 sdxl_train_network.py \
  --pretrained_model_name_or_path="<path to a non-banned SDXL 1.0 base checkpoint>" \
  --dataset_config="/path/to/char-<id>.toml" \
  --output_dir="/run/media/amirel/Amir1tb SSD/AI/Models/loras/<slug>" \
  --output_name="char-<id>" \
  --save_model_as=safetensors \
  --network_module=networks.lora \
  --network_dim=16 \
  --network_alpha=8 \
  --learning_rate=1e-4 \
  --unet_lr=1e-4 \
  --text_encoder_lr1=5e-6 \
  --text_encoder_lr2=5e-6 \
  --optimizer_type="AdamW8bit" \
  --lr_scheduler="cosine" \
  --max_train_steps=1500 \
  --save_every_n_epochs=1 \
  --mixed_precision="fp16" \
  --gradient_checkpointing \
  --cache_latents \
  --cache_text_encoder_outputs \
  --xformers
```

8 GB VRAM notes: `batch_size=1` (set in the dataset toml), `AdamW8bit`
(bitsandbytes, already installed), `--gradient_checkpointing`,
`--cache_latents` + `--cache_text_encoder_outputs`, and `fp16` mixed
precision are all load-bearing for fitting an SDXL LoRA run on the RTX 4070
Laptop's 8 GB. Do not drop them without re-checking VRAM headroom (ComfyUI
should not be running training-side while doing anything else on the GPU —
the CLAUDE.md fragmentation note applies here too).

## 5. GPU was busy at runbook-writing time

Per task instructions, **no training run was started** during this setup —
GPU had ComfyUI/other processes attached when this was written. Run the
commands above manually once a non-banned SDXL base checkpoint is sourced
(or once the krea2-gap in §1 is resolved) and the GPU is free.
