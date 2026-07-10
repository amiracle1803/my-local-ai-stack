# krea2 Lab Report (Work Order KREA-1)

**Date:** 2026-07-10
**Builder:** Opus (KREA-1 redispatch)
**Verdict in one line:** krea2 is **feasible as primary on 8 GB** (GGUF quants
fit under `--novram`) and its **native anime quality is excellent**, BUT it is
**BLOCKED**: the installed ComfyUI **0.24.0** has no Krea2 support. Krea2 needs
ComfyUI **0.25.0+**. Proof render + measured VRAM/sec-per-image are deferred
pending a ComfyUI core update, which needs Amir's approval (see Open Questions).

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

## 2. VRAM feasibility (8 GB, `--novram`)

Feasible by construction, not yet measured (render blocked — see §4). Rationale:
krea2 is the same ~12B DiT scale as FL.1-dev, which the existing install already
runs on this exact 8 GB card via city96 GGUF Q3/Q4 + `--novram`
(`flux1-dev-Q4_K_S.gguf` is on disk and in use). The Qwen3-VL-4B encoder (5.24 GB
fp8) runs first and is offloaded before the transformer loads; peak VRAM is the
streamed working layer + the 16-channel latent activations at 1216×704. Expect a
peak in the ~6–7.5 GB range and single-image wall time in the low minutes,
consistent with FLUX-12B behavior here. **Measured peak + sec/image will be
filled in after the ComfyUI update unblocks the render.**

## 3. Anime-style adherence assessment

Assessed from the model card's own anime samples (the model's native ceiling),
since a local render is blocked:

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

## 4. Proof render + validation (current state)

**Render: BLOCKED.** The intended 1216×704 render cannot run on ComfyUI 0.24.0.
Root cause is unambiguous and captured by the validator below: the `krea2`
CLIP type and the Krea2 UNET architecture do not exist in this build.

- `/system_stats` → `"comfyui_version": "0.24.0"`, torch `2.6.0+cu124` (pinned),
  Python 3.11.9, args `--novram --disable-cuda-malloc`.
- Live `CLIPLoader` / `CLIPLoaderGGUF` `type` enum (23 entries) ends at
  `ideogram4`; **no `krea2`, no `krea`**. Grep of `C:\AI\ComfyUI\comfy` for
  "krea" returns only coincidental tokenizer vocab tokens ("kreativ"), i.e. **no
  model support**. The vantagewithai native workflow is explicitly labeled
  "Native ComfyUI 0.25.0+ Krea2 workflow" — Krea2 landed after our snapshot.

**Validator output (`tools/validate_workflows.py`, live server :8188):**

```
ComfyUI workflow smoke-validation  (server http://127.0.0.1:8188)
==========================================================
character_sheet.json          PASS-with-note  ...expected PATCH-placeholder file(s) missing on node(s) 1,2,4
lora_dataset_prep.json        PASS-with-note  ...expected PATCH-placeholder file(s) missing on node(s) 1
ltx_ambient.json              PASS-with-note  ...expected PATCH-placeholder file(s) missing on node(s) 1,5
ltx_director.json             PASS-with-note  ...expected PATCH-placeholder file(s) missing on node(s) 1,12,5
mouth_sheet.json              PASS-with-note  ...expected PATCH-placeholder file(s) missing on node(s) 1,2,3,4
panel_img2img_lastframe.json  PASS-with-note  ...missing on node(s) 1,17,2,3,4,5,7,9
panel_txt2img.json            PASS-with-note  ...missing on node(s) 1,2,3,4,5,7,9
panel_txt2img_krea.json       FAIL            node 2 (CLIPLoader): type: 'krea2' not in (list of length 23); clip_name: 'qwen3vl_4b_fp8_scaled.safetensors' not in [...]
scene_plate.json              PASS-with-note  ...expected PATCH-placeholder file(s) missing on node(s) 1,2,3
wan_ti2v.json                 PASS-with-note  ...expected PATCH-placeholder file(s) missing on node(s) 6
==========================================================
PASS=0  PASS-with-note=9  FAIL=1  (total 10)
```

The single FAIL is the new krea template, failing *only* on the missing `krea2`
type (the clip_name mismatch line was because the encoder was mid-download at
validation time; it is now on disk). The 9 pre-existing templates still
PASS-with-note — **no regression** from the manifest edit. Note: `EmptySD3LatentImage`
did validate on 0.24.0 (it exists), so once the `krea2` type ships the template
is expected to queue cleanly.

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

**Verdict:** krea2 (Krea-2-Turbo) is a **strong primary-image candidate** and
should be adopted — pending (a) the ComfyUI update and (b) a measured render.
Nothing about the model itself disqualifies it; the block is purely the app
version. This does **not** meet the work order's hard-stop condition (which is
"cannot run on 8 GB in any offered form") — it can run; it just needs a newer
ComfyUI.

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

1. **ComfyUI update approval (the blocker).** krea2 needs ComfyUI **≥0.25.0**;
   the install is **0.24.0** and the handoff pins torch/pydantic + forbids
   builder git. Requesting approval to update ComfyUI **core** to the current
   release **holding the torch==2.6.0+cu124 / pydantic pins**, with a regression
   check that the accepted WF-1 templates (LTX/Wan/IPAdapter/flux) still validate
   9/9 and a rollback to the current git ref if anything breaks. This is the one
   action that unblocks the proof render, measured VRAM/sec-per-image, and the
   final adherence read on a real 1216×704 anime output. I did **not** do this
   unilaterally (shared, fragile, GPU-critical infra with an accepted deliverable
   riding on it — CLAUDE.md "don't replace working tooling unless I ask").
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
