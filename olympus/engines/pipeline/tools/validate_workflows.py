#!/usr/bin/env python3
"""Workflow validation script: validates that all patchable keys in manifest.json
exist as node inputs in their corresponding workflow JSON files.
"""
import json
import sys
from pathlib import Path


def extract_patchable_keys(workflow: dict, patchable_map: dict) -> set[str]:
    """Extract all input field paths referenced by patchable keys from workflow.

    Returns set of dotted paths like "1.unet_name", "11.text", etc.
    """
    found = set()
    for patch_key, workflow_path in patchable_map.items():
        # workflow_path format: "node_id.field" or "node_id.field.subfield"
        parts = workflow_path.split(".")
        if len(parts) < 2:
            continue
        node_id, field = parts[0], ".".join(parts[1:])

        if node_id in workflow:
            node = workflow[node_id]
            if "inputs" in node and field in node["inputs"]:
                found.add(workflow_path)
            elif "inputs" in node:
                # Check nested
                inputs = node["inputs"]
                for k in inputs:
                    if k.startswith(field):
                        found.add(workflow_path)
                        break
    return found


def validate_workflow(workflow_name: str, workflow: dict, patchable_map: dict) -> tuple[list[str], list[str]]:
    """Validate a single workflow against its patchable map.

    Returns (missing_keys, extra_keys) where:
    - missing_keys: patchable keys that don't exist in workflow
    - extra_keys: workflow inputs that aren't in patchable map (informational)
    """
    missing = []
    extra = []

    # Build set of all workflow input paths
    workflow_inputs = set()
    for node_id, node in workflow.items():
        if "inputs" in node:
            for field, value in node["inputs"].items():
                workflow_inputs.add(f"{node_id}.{field}")

    # Check each patchable key
    for patch_key, workflow_path in patchable_map.items():
        if workflow_path not in workflow_inputs:
            missing.append(f"{patch_key} -> {workflow_path}")

    # Check for extra workflow inputs not in patchable map (optional, warn only)
    mapped = set(patchable_map.values())
    unmapped = workflow_inputs - mapped
    if unmapped:
        extra = sorted(unmapped)

    return missing, extra


def main():
    manifest_path = Path("olympus/engines/pipeline/workflows/manifest.json")
    if not manifest_path.exists():
        print(f"ERROR: manifest.json not found at {manifest_path}")
        return 1

    with open(manifest_path) as f:
        manifest = json.load(f)

    templates = manifest.get("templates", {})
    workflows_dir = Path("olympus/engines/pipeline/workflows")

    all_ok = True
    total_missing = 0
    total_checked = 0

    print("=" * 80)
    print("WORKFLOW VALIDATION: manifest.json patchable keys vs workflow inputs")
    print("=" * 80)

    for template_name, template_info in templates.items():
        if template_name.endswith(".json"):
            status = template_info.get("status", "unknown")
            if status in ("deprecated", "visual_workflow"):
                print(f"\n{template_name}: SKIPPED (status={status})")
                continue

            workflow_path = workflows_dir / template_name
            if not workflow_path.exists():
                print(f"\n{template_name}: MISSING FILE")
                all_ok = False
                continue

            patchable = template_info.get("patchable", {})
            if not patchable:
                print(f"\n{template_name}: NO PATCHABLE KEYS DEFINED")
                continue

            try:
                with open(workflow_path) as f:
                    workflow = json.load(f)
            except json.JSONDecodeError as e:
                print(f"\n{template_name}: INVALID JSON - {e}")
                all_ok = False
                continue

            missing, extra = validate_workflow(template_name, workflow, patchable)

            print(f"\n{template_name}: {len(patchable)} patchable keys defined")
            if missing:
                print(f"  ❌ MISSING ({len(missing)}):")
                for m in missing:
                    print(f"    - {m}")
                all_ok = False
                total_missing += len(missing)
            else:
                print(f"  ✅ All {len(patchable)} patchable keys found in workflow")

            if extra:
                print(f"  ⚠️  UNMAPPED workflow inputs ({len(extra)}):")
                for e in sorted(extra)[:10]:  # limit output
                    print(f"    - {e}")
                if len(extra) > 10:
                    print(f"    ... and {len(extra) - 10} more")

            total_checked += len(patchable)

    print("\n" + "=" * 80)
    if all_ok:
        print(f"✅ VALIDATION PASSED: {total_checked} patchable keys checked, 0 missing")
        return 0
    else:
        print(f"❌ VALIDATION FAILED: {total_missing} missing patchable keys out of {total_checked} checked")
        return 1


if __name__ == "__main__":
    sys.exit(main())