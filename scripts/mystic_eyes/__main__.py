#!/usr/bin/env python3
"""
__main__.py — single CLI entry point for the Mystic Eyes ComfyUI pipeline.

Run as:  python -m scripts.mystic_eyes <subcommand> [options]

Subcommands:
  parse       Extract character entries from the appearance text.
  prompts     Build CLIP positive/negative prompts from a characters JSON.
  workflows   Write one workflow per character (batch).
  character   Build a single-character workflow.
  scene       Build one scene workflow (images + style notes).
  episode     Build all scene workflows for an episode manifest.
  queue       Queue workflows to the ComfyUI server.

This replaces a dozen overlapping root-level scripts with one coherent tool.
"""

import argparse
import sys

from . import config, parse, prompts, workflows, queue


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.mystic_eyes",
        description="Mystic Eyes ComfyUI pipeline tools.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # parse
    sp = sub.add_parser("parse", help="extract character entries from the appearance file")
    sp.add_argument("--strategy", choices=sorted(parse.STRATEGIES), default="blocks",
                    help="how to split entries (heuristic/names/blocks)")
    sp.add_argument("--output", default=None, help="override output JSON path")

    # prompts
    sp = sub.add_parser("prompts", help="build CLIP prompts from a characters JSON")
    sp.add_argument("--input", required=True, help="characters JSON path")
    sp.add_argument("--output", required=True, help="output CLIP prompts JSON path")
    sp.add_argument("--desc-field", default="description", help="description field name")
    sp.add_argument("--words", type=int, default=None, help="truncate description to N words")
    sp.add_argument("--chars", type=int, default=None, help="truncate description to N chars")

    # workflows (batch)
    sp = sub.add_parser("workflows", help="write one workflow per character (batch)")
    sp.add_argument("--prompts", help="CLIP prompts JSON (else built from --characters)")
    sp.add_argument("--characters", help="characters JSON to build prompts from")
    sp.add_argument("--output", default=None, help="output directory")

    # character
    sp = sub.add_parser("character", help="build a single-character workflow")
    sp.add_argument("--character", required=True, help="character name")
    sp.add_argument("--prompts", help="CLIP prompts JSON (else built from --characters)")
    sp.add_argument("--characters", help="characters JSON to build prompts from")
    sp.add_argument("--output", required=True, help="output workflow JSON path")

    # scene
    sp = sub.add_parser("scene", help="build one scene workflow")
    sp.add_argument("--scene", required=True, help="scene JSON path")
    sp.add_argument("--prompts", help="CLIP prompts JSON (else built from --characters)")
    sp.add_argument("--characters", help="characters JSON to build prompts from")
    sp.add_argument("--output", required=True, help="output workflow JSON path")

    # episode
    sp = sub.add_parser("episode", help="build all scene workflows for an episode manifest")
    sp.add_argument("--manifest", required=True, help="episode manifest JSON path")
    sp.add_argument("--prompts", help="CLIP prompts JSON (else built from --characters)")
    sp.add_argument("--characters", help="characters JSON to build prompts from")
    sp.add_argument("--outdir", required=True, help="output directory")

    # queue
    sp = sub.add_parser("queue", help="queue workflows to the ComfyUI server")
    sp.add_argument("--dir", required=True, help="directory of *.json workflows")
    sp.add_argument("--url", default="http://localhost:8188/prompt", help="ComfyUI /prompt URL")
    sp.add_argument("--convert", action="store_true",
                    help="convert workflows to API prompt format before queueing")
    sp.add_argument("--delay", type=float, default=0, help="seconds to wait between queues")

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cmd = args.command

    if cmd == "parse":
        return parse.main(args.strategy, args.output)
    if cmd == "prompts":
        return prompts.main(args.input, args.output, args.desc_field, args.words, args.chars)
    if cmd == "queue":
        return queue.main(args.dir, args.url, args.convert, args.delay)
    # workflows / character / scene / episode share the workflow dispatcher
    return workflows.main(cmd, args.prompts, args.characters,
                          getattr(args, "character", None), getattr(args, "output", None),
                          getattr(args, "scene", None), getattr(args, "manifest", None),
                          getattr(args, "outdir", None))


if __name__ == "__main__":
    sys.exit(main())
