#!/usr/bin/env python3
"""
patch_f5tts.py — Apply Windows-compatibility patches to F5-TTS, vocos, and Fish Speech 1.5.
Safe to re-run: each patch checks whether it's already applied before writing.
Patches are silently skipped when the target file is missing (e.g. package not installed).
"""
import os, re, sys


def site_packages():
    for p in sys.path:
        if os.path.isdir(p) and "site-packages" in p:
            return p
    raise SystemExit("  [ERROR] Could not find site-packages in sys.path")


SITE = site_packages()


def fp(rel):
    return os.path.join(SITE, rel.replace("/", os.sep))


def clear_pyc(filepath):
    pycache = os.path.join(os.path.dirname(filepath), "__pycache__")
    stem = os.path.splitext(os.path.basename(filepath))[0]
    if os.path.isdir(pycache):
        for fn in os.listdir(pycache):
            if fn.startswith(stem + "."):
                try:
                    os.remove(os.path.join(pycache, fn))
                except OSError:
                    pass


def patch_exact(rel, old, new, label):
    f = fp(rel)
    if not os.path.isfile(f):
        print(f"    skip  (missing):  {label}")
        return False
    txt = open(f, encoding="utf-8").read()
    if old not in txt:
        print(f"    ok    (already):  {label}")
        return False
    open(f, "w", encoding="utf-8").write(txt.replace(old, new, 1))
    clear_pyc(f)
    print(f"    done: {label}")
    return True


def patch_regex(rel, pattern, replacement, label, already_marker):
    f = fp(rel)
    if not os.path.isfile(f):
        print(f"    skip  (missing):  {label}")
        return False
    txt = open(f, encoding="utf-8").read()
    if already_marker in txt:
        print(f"    ok    (already):  {label}")
        return False
    new_txt, n = re.subn(pattern, replacement, txt)
    if n == 0:
        print(f"    skip  (no match): {label}")
        return False
    open(f, "w", encoding="utf-8").write(new_txt)
    clear_pyc(f)
    print(f"    done: {label}")
    return True


print("  Patching F5-TTS + vocos for Windows...")
print()

# ── 1. f5_tts/api.py ─────────────────────────────────────────────────────────
# Replace cached_path (pulls google-cloud dep chain) with hf_hub_download

patch_exact(
    "f5_tts/api.py",
    "from cached_path import cached_path",
    "from huggingface_hub import hf_hub_download as _hf_hub_download",
    "api.py: swap cached_path import → hf_hub_download",
)

# Handle both single-line and multi-line formats of the cached_path() call
patch_regex(
    "f5_tts/api.py",
    r"ckpt_file\s*=\s*cached_path\(\s*"
    r'f"hf://SWivid/\{repo_name\}/\{model\}/model_\{ckpt_step\}\.\{ckpt_type\}"\s*\)',
    (
        "ckpt_file = _hf_hub_download(\n"
        "                repo_id=f\"SWivid/{repo_name}\",\n"
        "                filename=f\"{model}/model_{ckpt_step}.{ckpt_type}\",\n"
        "                cache_dir=hf_cache_dir,\n"
        "            )"
    ),
    "api.py: replace cached_path() call with hf_hub_download()",
    already_marker="_hf_hub_download(",
)

print()

# ── 2. f5_tts/model/__init__.py ──────────────────────────────────────────────
# Remove Trainer import (trainer.py pulls wandb which is heavy and optional)

patch_exact(
    "f5_tts/model/__init__.py",
    "from f5_tts.model.trainer import Trainer\n",
    "",
    "__init__.py: remove Trainer import",
)

# __all__ may have Trainer in several positions — try each variant
for variant in ('"Trainer", ', ', "Trainer"', '"Trainer"'):
    patch_exact(
        "f5_tts/model/__init__.py",
        variant,
        "",
        f'__init__.py: remove Trainer from __all__ ({variant.strip()})',
    )

print()

# ── 3. vocos/feature_extractors.py ───────────────────────────────────────────
# encodec fails to build on Windows; guard import so vocos still loads

patch_exact(
    "vocos/feature_extractors.py",
    "from encodec import EncodecModel",
    (
        "try:\n"
        "    from encodec import EncodecModel\n"
        "except ImportError:\n"
        "    EncodecModel = None"
    ),
    "feature_extractors.py: lazy encodec import (Windows build fix)",
)

print()

# ── 4. f5_tts/infer/utils_infer.py ───────────────────────────────────────────
# Sequential chunk processing — ThreadPoolExecutor on a single CUDA stream
# adds thread-contention overhead without any real GPU parallelism benefit.

patch_exact(
    "f5_tts/infer/utils_infer.py",
    (
        "        with ThreadPoolExecutor() as executor:\n"
        "            futures = [executor.submit(infer_single_process, gen_text) for gen_text in gen_text_batches]\n"
        "            for future in progress.tqdm(futures) if progress is not None else futures:\n"
        "                result = future.result()\n"
        "                if result:\n"
        "                    generated_wave, generated_mel_spec = result\n"
        "                    generated_waves.append(generated_wave)\n"
        "                    spectrograms.append(generated_mel_spec)"
    ),
    (
        "        # Sequential: CUDA ops share one stream, threads add contention with no GPU benefit.\n"
        "        batch_iter = progress.tqdm(gen_text_batches) if progress is not None else gen_text_batches\n"
        "        for gen_text in batch_iter:\n"
        "            result = infer_single_process(gen_text)\n"
        "            if result:\n"
        "                generated_wave, generated_mel_spec = result\n"
        "                generated_waves.append(generated_wave)\n"
        "                spectrograms.append(generated_mel_spec)"
    ),
    "utils_infer.py: replace ThreadPoolExecutor with sequential loop",
)

# Remove noisy debug prints that spam the terminal

patch_exact(
    "f5_tts/infer/utils_infer.py",
    '\n    print("\\nref_text  ", ref_text)\n',
    "\n",
    "utils_infer.py: remove ref_text debug print",
)

patch_exact(
    "f5_tts/infer/utils_infer.py",
    (
        "    for i, gen_text_i in enumerate(gen_text_batches):\n"
        '        print(f"gen_text {i}", gen_text_i)\n'
        '    print("\\n")\n'
    ),
    "",
    "utils_infer.py: remove gen_text debug prints",
)

print()

# ── Fish Speech 1.5 Windows patches ──────────────────────────────────────────
# Safe to run even if fish-speech is not installed: each patch checks for the
# file before touching it and skips silently when absent.

print("  Patching Fish Speech 1.5 for Windows (if installed)...")
print()

# ── 5. Disable torch.compile in the LLaMA model ──────────────────────────────
# torch.compile crashes on Windows with PyTorch 2.6 (inductor / triton absent).
# Fish Speech gates compilation behind a `compile` flag, but the decorator form
# can slip through; patch both the argument-less and argument forms.

patch_exact(
    "fish_speech/models/text2semantic/llama.py",
    "@torch.compile",
    "# @torch.compile  # disabled: inductor/triton not supported on Windows",
    "llama.py: disable @torch.compile decorator (Windows PyTorch 2.6)",
)

patch_regex(
    "fish_speech/models/text2semantic/llama.py",
    r'(model\s*=\s*)torch\.compile\(model[^)]*\)',
    r'\1model  # torch.compile disabled on Windows',
    "llama.py: disable torch.compile() call (Windows PyTorch 2.6)",
    already_marker="torch.compile disabled on Windows",
)

# ── 6. Guard flash_attn import in the LLaMA model ────────────────────────────
# flash_attn requires a CUDA build step that fails on Windows without a full
# build environment.  Wrap in try/except so the rest of the model still loads.

patch_exact(
    "fish_speech/models/text2semantic/llama.py",
    "from flash_attn import flash_attn_func",
    (
        "try:\n"
        "    from flash_attn import flash_attn_func\n"
        "except ImportError:\n"
        "    flash_attn_func = None"
    ),
    "llama.py: lazy flash_attn import (Windows build fix)",
)

patch_exact(
    "fish_speech/models/text2semantic/llama.py",
    "from flash_attn.bert_padding import pad_input, unpad_input",
    (
        "try:\n"
        "    from flash_attn.bert_padding import pad_input, unpad_input\n"
        "except ImportError:\n"
        "    pad_input = unpad_input = None"
    ),
    "llama.py: lazy flash_attn.bert_padding import (Windows build fix)",
)

# ── 7. Guard flash_attn in the VQGAN / firefly modules ───────────────────────

for _rel in (
    "fish_speech/models/vqgan/modules/transformer.py",
    "fish_speech/models/vqgan/modules/fsq.py",
    "fish_speech/models/vqgan/firefly.py",
):
    patch_exact(
        _rel,
        "from flash_attn import flash_attn_func",
        (
            "try:\n"
            "    from flash_attn import flash_attn_func\n"
            "except ImportError:\n"
            "    flash_attn_func = None"
        ),
        f"{_rel.split('/')[-1]}: lazy flash_attn import (Windows build fix)",
    )

# ── 8. Remove torch.compile decorator from VQGAN encoder/decoder ─────────────

for _rel in (
    "fish_speech/models/vqgan/modules/transformer.py",
    "fish_speech/models/vqgan/firefly.py",
):
    patch_exact(
        _rel,
        "@torch.compile",
        "# @torch.compile  # disabled: inductor/triton not supported on Windows",
        f"{_rel.split('/')[-1]}: disable @torch.compile (Windows PyTorch 2.6)",
    )

# ── 9. Guard mamba_ssm import (optional accelerator — may fail on Windows) ───

patch_exact(
    "fish_speech/models/text2semantic/llama.py",
    "from mamba_ssm import Mamba",
    (
        "try:\n"
        "    from mamba_ssm import Mamba\n"
        "except ImportError:\n"
        "    Mamba = None"
    ),
    "llama.py: lazy mamba_ssm import (optional, fails on Windows)",
)

print()
print("  All patches applied.")
