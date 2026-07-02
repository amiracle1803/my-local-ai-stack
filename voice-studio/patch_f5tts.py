#!/usr/bin/env python3
"""
patch_f5tts.py — Apply Windows-compatibility patches to F5-TTS and vocos.
Safe to re-run: each patch checks whether it's already applied before writing.
Patches are silently skipped when the target file is missing (e.g. package not installed).

Ported from real-natural-voices/patch_f5tts.py. The Fish Speech patch set from
that file was dropped here -- neither source app (real-natural-voices,
second-speech-filter-workflow) actually used Fish Speech; it was dead code.
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
print("  All patches applied.")
