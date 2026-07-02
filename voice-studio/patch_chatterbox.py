#!/usr/bin/env python3
"""
patch_chatterbox.py — Fix a cfg_weight=0.0 crash in chatterbox-tts.

Root cause: chatterbox/tts.py's generate() only duplicates text_tokens to
batch=2 when cfg_weight > 0 (CFG needs a conditional + unconditional pass).
But chatterbox/models/t3/t3.py's inference() duplicates bos_embed to
batch=2 UNCONDITIONALLY, and later unconditionally splits logits into
cond/uncond halves and re-duplicates next_token_embed each generation
step. Any call with cfg_weight=0.0 -- which Voice Studio's own UI labels
"Off (fast)", i.e. an intentionally supported mode, not an edge case --
crashes with:
    RuntimeError: Sizes of tensors must match except in dimension 1.
    Expected size 1 but got size 2 for tensor number 1 in the list.

Fix: gate all three duplication points on a single `cfg_active` flag that
mirrors tts.py's own decision, instead of assuming CFG is always on.

Safe to re-run: checks whether already applied before writing.
"""
import os, sys


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
        print(f"    ok    (already, or upstream changed):  {label}")
        return False
    open(f, "w", encoding="utf-8").write(txt.replace(old, new, 1))
    clear_pyc(f)
    print(f"    done: {label}")
    return True


print("  Patching chatterbox-tts: fix cfg_weight=0.0 crash...")
print()

patch_exact(
    "chatterbox/models/t3/t3.py",
    (
        "        # batch_size=2 for CFG\n"
        "        bos_embed = torch.cat([bos_embed, bos_embed])\n"
        "\n"
        "        # Combine condition and BOS token for the initial input\n"
        "        inputs_embeds = torch.cat([embeds, bos_embed], dim=1)"
    ),
    (
        "        # batch_size=2 for CFG -- only when `embeds` itself carries two\n"
        "        # batches. tts.py only doubles text_tokens (and therefore embeds)\n"
        "        # when cfg_weight > 0; duplicating bos_embed unconditionally here\n"
        "        # crashed cfg_weight=0.0 with a tensor-size mismatch.\n"
        "        cfg_active = embeds.size(0) > 1\n"
        "        if cfg_active:\n"
        "            bos_embed = torch.cat([bos_embed, bos_embed])\n"
        "\n"
        "        # Combine condition and BOS token for the initial input\n"
        "        inputs_embeds = torch.cat([embeds, bos_embed], dim=1)"
    ),
    "t3.py: make bos_embed CFG duplication conditional on cfg_active",
)

patch_exact(
    "chatterbox/models/t3/t3.py",
    (
        "            logits_step = output.logits[:, -1, :]\n"
        "            # CFG combine  → (1, V)\n"
        "            cond   = logits_step[0:1, :]\n"
        "            uncond = logits_step[1:2, :]\n"
        "            cfg = torch.as_tensor(cfg_weight, device=cond.device, dtype=cond.dtype)\n"
        "            logits = cond + cfg * (cond - uncond)"
    ),
    (
        "            logits_step = output.logits[:, -1, :]\n"
        "            if cfg_active:\n"
        "                # CFG combine  → (1, V)\n"
        "                cond   = logits_step[0:1, :]\n"
        "                uncond = logits_step[1:2, :]\n"
        "                cfg = torch.as_tensor(cfg_weight, device=cond.device, dtype=cond.dtype)\n"
        "                logits = cond + cfg * (cond - uncond)\n"
        "            else:\n"
        "                # cfg_weight == 0.0: no unconditional pass was run, use the single batch as-is\n"
        "                logits = logits_step"
    ),
    "t3.py: make cond/uncond CFG combine conditional on cfg_active",
)

patch_exact(
    "chatterbox/models/t3/t3.py",
    (
        "            #  For CFG\n"
        "            next_token_embed = torch.cat([next_token_embed, next_token_embed])"
    ),
    (
        "            #  For CFG\n"
        "            if cfg_active:\n"
        "                next_token_embed = torch.cat([next_token_embed, next_token_embed])"
    ),
    "t3.py: make next_token_embed CFG duplication conditional on cfg_active",
)

print()
print("  All patches applied.")
