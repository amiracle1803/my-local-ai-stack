# krea2 Lab Report (Work Order KREA-1)

**Date:** 2026-07-10 (measured sections filled same day after COMFY-UPDATE)
**Builder:** Opus (KREA-1 redispatch); measured render by COMFY-UPDATE builder
**Verdict in one line:** krea2 (Krea-2-Turbo, GGUF Q4_K_S) is **PROVEN as
primary on this 8 GB card**: ComfyUI was updated 0.24.0 → **0.27.1** (torch /
pydantic pins held, 10/10 templates revalidated), and the 1216×704 / 8-step
proof render completed in **113.7 s** at a peak of **7782 MiB VRAM** with a
clean, on-prompt cel-shaded anime output. **ADOPT as image_primary.**

---

## 1. Resolved identity, architecture, files, license

**Model:** `krea/Krea-2-Turbo` on Hugging Face (accessed as `amiracle1803`;
repo is **public, not gated**). Released 2026-06-22 by Krea.ai, Inc. This is the
target Amir mandated; **FLUX.1-Krea-dev was NOT downloaded, loaded, or used**
(ban-list §5.3b honored). No banned model (z-anime-distill, wai-illustrious,
NoobAI-XL) was touched.

**Architecture — this is a NEW arch, NOT SDXL and NOT FLUX:**

| Component | Class | Notes |
|---|---|---|
| Pipeline | `Krea2Pipeline` (diffusers 0.39.0.dev) | custom; `is_distilled: true` |
| Transformer | `Krea2Transformer2DModel` | **12B-parameter Diffusion Transformer**, 28 layers, in_channels 64, patch_size 2, MMDiT-style with 12 dedicated text layers |
| Text encoder | `Qwen3VLModel` (Qwen3-VL **4B**) | hidden_size 2560, 36 layers; pipeline reads hidden states from 12 selected layers [2,5,8…35]. **The 8B Qwen3-VL already on disk is the WRONG size** (hidden 4096) — the 4B is required. |
| Tokenizer | `Qwen2Tokenizer` | |
| VAE | `AutoencoderKLQwenImage` | the **Qwen-Image VAE**, 16-channel latent (so the ComfyUI latent node must be `EmptySD3LatentImage`, NOT `EmptyLatentImage`) |
| Scheduler | `FlowMatchEulerDiscreteScheduler` | flow-matching |

Architecturally krea2 is a **cousin of Qwen-Image** (shares the Qwen-Image VAE
and a Qwen3-VL text encoder). That is what makes it runnable in ComfyUI via the
Qwen-Image code path — once the ComfyUI version supports the `krea2` type.

**Recommended sampling (Turbo, from the model card):** **8 steps, guidance 0.0**
(diffusers `guidance_scale=0.0` == ComfyUI KSampler `cfg=1.0`), `mu=1.15`.
Community ComfyUI workflows use `euler`/`simple` (gguf-org) or `er_sde`/`simple`
(vantagewithai), 8 steps, cfg 1.0, negative via `ConditioningZeroOut` (CFG is
distilled out, so a text negative has no effect). The template uses euler/simple.

**License:** **Krea 2 Community License** (`license: other`,
`license_name: krea-2-community-license`, LICENSE.pdf in the repo). Key point for
this project: it is an open-weights license that **requires deployers to
implement content-filtering / review** to prevent unlawful or policy-violating
outputs. For a local, personal recap pipeline this is low-friction, but it is a
license obligation Amir should be aware of if outputs are ever published.

**File choice for 8 GB VRAM (GGUF via the installed city96 ComfyUI-GGUF):**

| File | Repo | Bytes (verified) | Dir on disk |
|---|---|---|---|
| `krea2_turbo-Q4_K_S.gguf` (12B transformer, ~Q4) | `vantagewithai/Krea-2-Turbo-GGUF` | 7,486,289,184 | `C:\AI\ComfyUI\models\unet\` |
| `qwen3vl_4b_fp8_scaled.safetensors` (text encoder) | `Comfy-Org/Qwen3-VL` | 5,242,467,968 | `C:\AI\ComfyUI\models\text_encoders\` |
| `qwen_image_vae.safetensors` (VAE) | `Comfy-Org/Qwen-Image_ComfyUI` | 253,806,246 | `C:\AI\ComfyUI\models\vae\` |

All three are new to disk (inventory confirmed none present). Every byte size
matches the HF listing exactly. Total ~13 GB; C: had 96.8 GB free (staged on C:).
Full-precision alternatives left un-downloaded: `turbo.safetensors` (26.3 GB
single-file bf16) and the 3-shard diffusers transformer (~26 GB) — neither fits
8 GB. GGUF is the only viable path. Quant ladder available if Q4_K_S OOMs:
Q3_K_S (6.01 GB), Q2_K (4.89 GB) in the same repo; even smaller IQ quants exist
in `gguf-org/krea-2-gguf`.

**Why Q4_K_S:** under `--novram` the transformer stays in system RAM (32 GB) and
streams per-layer to the GPU, so the quant size mostly drives RAM, not VRAM peak.
Q4_K_S is the standard quality/size balance and matches the vantagewithai native
workflow's default. Q3/Q2 are the documented OOM fallbacks.

## 2. VRAM feasibility (8 GB, `--novram`) — MEASURED 2026-07-10

Measured on the real proof render (ComfyUI 0.27.1, `--novram
--disable-cuda-malloc`, 1216×704, 8 steps, euler/simple, cfg 1.0):

| Metric | Value |
|---|---|
| Wall clock (queue → history success) | **113.7 s** (~14 s/step + encoder/VAE overhead) |
| Peak VRAM (nvidia-smi, 5 s polling) | **7782 MiB** of 8188 MiB |
| VRAM profile | ~7.1–7.3 GiB during text-encode, ~7.7–7.8 GiB plateau during DiT sampling, drop to ~2.8 GiB at VAE decode |
| Output | `C:\AI\ComfyUI\output\krea_panel_00001_.png`, 1216×704 RGB, 574,987 bytes |
| OOM / retry | none — first attempt succeeded at full 1216×704 |

Headroom is thin (~400 MiB at peak) but stable; note the baseline before the
run already held ~1 GiB from other processes. If future runs OOM (e.g. with a
LoRA loaded), the documented fallbacks are Q3_K_S (6.01 GB) / Q2_K (4.89 GB)
quants or 896×512. The prior estimate ("peak ~6–7.5 GB, low minutes per
image") was accurate.

## 3. Anime-style adherence assessment

**Local proof render (2026-07-10, prompt: "anime illustration, silver-haired
girl in a red coat standing on a cliff at dusk, cel shading", 8 steps, seed 0):**
every prompt element landed — silver-haired girl (with unprompted but coherent
extras: black hairband, red hair ribbon, backpack), red hooded coat over a
white lace dress, standing on a rocky cliff edge, dusk gradient sky
(blue → pink) with a distant mountain silhouette line. The style is clean flat
**cel shading** with crisp linework — genuinely anime, not "photoreal with
anime tags". Composition is strong (rule-of-thirds character placement, empty
sky negative space usable for text overlay). No visible artifacts: face and
eyes are clean at this small character scale, no extra limbs (hands are in
pockets), no banding in the sky gradient, no watermark. This is 8-step Turbo
output at cfg 1.0 with no LoRA — an excellent floor for the recap pipeline.

Prior assessment from the model card's own anime samples (the model's native
ceiling), written while the local render was blocked:

- **`images/33.jpg`** ("1990s vintage anime style cel animation", dense student
  crowd): production-grade 1990s cel look — clean linework, flat cel shading,
  period-accurate designs, and **~15 characters all on-model in one frame**.
  Multi-character coherence is far beyond what SDXL anime bases hold.
- **`images/13.jpg`** (anime forest, boy + girl + creatures): **Studio
  Ghibli-grade** hand-painted background with correct character designs and
  natural lighting.

Combined with krea2's long **natural-language** prompt following (the card's
prompts are paragraph-length scene descriptions) and native legible text
rendering, this is a **strong fit for the recap-anime goal** — plausibly better
than the banned SDXL anime checkpoints for the "traditional / cel / Ghibli"
aesthetic, and dramatically better at prompt adherence and multi-subject scenes.
Caveat: the card leans toward traditional/cel and painterly looks; adherence to a
specific *modern moe / light-novel* anime style will depend on a style LoRA
(M4) — the base is broad rather than a narrow anime specialist.

## 4. Proof render + validation — COMPLETED 2026-07-10 (post COMFY-UPDATE)

**The 0.24.0 block was cleared by work order COMFY-UPDATE:** ComfyUI updated
`822aca19` (v0.24.0-60) → tag **v0.27.1** (`c2638ce6`), torch `2.6.0+cu124` and
pydantic `2.12.3` pins held, local patches reapplied. Live `/object_info` on
0.27.1 now lists `krea2` in the `CLIPLoader.type` enum (25 entries) and
`qwen3vl_4b_fp8_scaled.safetensors` in `clip_name`.

**Render: SUCCESS** — prompt_id `361e712a-6103-48aa-86be-55686ea32da2`,
`/history` status `success / completed=True`, no node errors, no OOM.
1216×704, 8 steps, 113.7 s wall, peak 7782 MiB VRAM (details §2, quality §3).
Output: `C:\AI\ComfyUI\output\krea_panel_00001_.png` (574,987 bytes).

**Validator output on 0.27.1 (`tools/validate_workflows.py`, live :8188):**

```
ComfyUI workflow smoke-validation  (server http://127.0.0.1:8188)
==========================================================
character_sheet.json          PASS-with-note  aliases resolved; expected PATCH-placeholder file(s) missing on node(s) 1,2,4
lora_dataset_prep.json        PASS-with-note  aliases resolved; clean queue (cancelled before generation)
ltx_ambient.json              PASS-with-note  aliases resolved; clean queue (cancelled before generation)
ltx_director.json             PASS-with-note  aliases resolved; clean queue (cancelled before generation)
mouth_sheet.json              PASS-with-note  aliases resolved; expected PATCH-placeholder file(s) missing on node(s) 1,2
panel_img2img_lastframe.json  PASS-with-note  aliases resolved; expected PATCH-placeholder file(s) missing on node(s) 1,2,3,4,5
panel_txt2img.json            PASS-with-note  aliases resolved; expected PATCH-placeholder file(s) missing on node(s) 1,2,3,4,5
panel_txt2img_krea.json       PASS-with-note  aliases resolved; clean queue (cancelled before generation)
scene_plate.json              PASS-with-note  aliases resolved; expected PATCH-placeholder file(s) missing on node(s) 1,2,3
wan_ti2v.json                 PASS-with-note  aliases resolved; clean queue (cancelled before generation)
==========================================================
PASS=0  PASS-with-note=10  FAIL=0  (total 10)
```

All 9 pre-existing templates still pass (**no regression** from the 0.27.1
update) and `panel_txt2img_krea.json` moved FAIL → PASS-with-note, then
rendered for real.

<details><summary>Historical: the 0.24.0 blocked state (for the record)</summary>

On 0.24.0 the `CLIPLoader.type` enum (23 entries) ended at `ideogram4` with no
`krea2`; the krea template was the single FAIL (9 PASS-with-note / 1 FAIL) and
the render could not run. Krea2 support landed in ComfyUI 0.25.0+.

</details>

**Template built:** `olympus/engines/pipeline/workflows/panel_txt2img_krea.json`
(API format, stable `_meta` titles: CKPT / CLIP_LOADER / VAE_LOADER / PROMPT_POS
/ PROMPT_NEG / LATENT / SAMPLER / DECODE / SAVE) with a manifest entry (status
`BLOCKED-comfyui-version`, full patch map + notes). Graph:
`UnetLoaderGGUF → KSampler(8 steps, cfg 1.0, euler/simple)`;
`CLIPLoader(type=krea2) → CLIPTextEncode(POS)`; negative = `ConditioningZeroOut`;
`VAELoader(qwen_image_vae)`; `EmptySD3LatentImage(1216×704)`. It is authored
correctly for the real (0.25.0+) architecture and will pass validation + render
once ComfyUI is updated.

## 5. Verdict + what M4 must add

**Verdict (final, 2026-07-10):** krea2 (Krea-2-Turbo, GGUF Q4_K_S) **ADOPT as
image_primary**. Both former conditions are now met: (a) ComfyUI updated to
0.27.1 with pins held and zero template regressions, and (b) the measured
1216×704 render succeeded first-try in 113.7 s at 7782 MiB peak with clean,
fully on-prompt cel-shaded anime output. The hard-stop condition ("cannot run
on 8 GB in any offered form") is definitively not met — it runs.

**M4 additions this changes (krea2 is a different arch, so the SDXL-era plan in
design §5.3b must be revised for image stages):**

1. **Style LoRA path:** krea2 uses its **own LoRA format** (Krea2Transformer),
   NOT SDXL LoRAs. The existing `il_anime_model_turn` and `Hyper-SDXL` LoRAs are
   **incompatible** and cannot be stacked on krea2. Official krea2 style LoRAs
   already exist (`krea/Krea-2-LoRA-retroanime`, `-darkbrush`, `-softwatercolor`,
   etc.) and load via a krea2-aware LoRA loader. A pipeline **style LoRA** should
   be a krea2 LoRA (train via the `multimodalart/krea2-lora-trainer` /
   `Ivan0204/krea2-lora-trainer` spaces, or locally on the krea2 arch).
2. **Turnaround / character-sheet equivalent:** the SDXL turnaround LoRA does not
   apply. Options for on-model turnarounds: (a) train a **krea2 character LoRA**
   per character (the mandatory M4 character-LoRA gate now targets krea2, not
   SDXL), or (b) use krea2's strong prompt following + a krea2 turnaround LoRA if
   one is trained. Speed distillation is already **built into Turbo** (8 steps),
   so no separate Hyper/speed LoRA is needed.
3. **Reference conditioning:** SDXL **IPAdapter does not work on krea2**. krea2's
   native equivalents are **`krea2-identity-edit`** (identity/character
   reference) and **`krea2-style-reference`** (style reference), plus a
   `krea-2-depth-controlnet` for pose/composition — these are the M4 building
   blocks for character-ref + scene-plate conditioning, replacing the dual
   IPAdapter graph in `panel_txt2img.json`.
4. **Latent/VAE plumbing:** image stages on krea2 must use the Qwen-Image VAE +
   16-ch (`EmptySD3LatentImage`) latents, not the SD1.5/SDXL 4-ch path.

## 6. Open questions for Amir (escalate via Fable)

1. ~~**ComfyUI update approval (the blocker).**~~ **RESOLVED 2026-07-10 by
   work order COMFY-UPDATE:** ComfyUI updated to v0.27.1 with the
   torch==2.6.0+cu124 / pydantic 2.12.3 pins held; all 9 prior templates
   revalidated with no regression; rollback ref `822aca19` (plus local-patch
   checkpoint commit `834b2568`) recorded in ComfyUI's own git.
2. **Quant confirmation.** Q4_K_S staged as primary; confirm OK, or prefer
   Q3_K_S/Q2_K for more VRAM headroom (measurable once unblocked).
3. **License note.** Krea 2 Community License requires deployer content
   filtering if outputs are published — fine for local/personal use; flagging it.
4. **Design doc §5.3b** still describes the SDXL image path (Hyper LoRA, turnaround
   LoRA, dual IPAdapter). If krea2 is confirmed primary, §5.3b's image-stage
   templates (`character_sheet`, `panel_txt2img`, `panel_img2img_lastframe`,
   `scene_plate`, `mouth_sheet`) need a krea2 rewrite in M4 — they currently
   assume SDXL and would run only on the fallback `flux1-schnell` path.

## Appendix — no backup run

Per the work order, git and `scripts\backup-code.ps1` were **not** run (Fable
commits). Files created/modified this order:
`olympus/engines/pipeline/workflows/panel_txt2img_krea.json` (new),
`olympus/engines/pipeline/workflows/manifest.json` (added krea entry),
`docs/planning/krea2-lab-report.md` (this file), plus the three model files
staged under `C:\AI\ComfyUI\models\`.
