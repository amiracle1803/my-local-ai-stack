#!/usr/bin/env python3
"""Convert ComfyUI API-format workflow JSON to UI-format for the Load menu.

API format: {"1": {...}, "2": {...}}  (flat dict keyed by node ID string)
UI format:  {"nodes": [...], "links": [...], "last_link_id": N, "version": 0.4}

Usage:
    python api_to_ui_converter.py <input.json> [output.json]
    python api_to_ui_converter.py --all <dir>   # convert every .json in dir

The converter:
1. Transforms each flat node into a UI node object with position, inputs, outputs
2. Builds the links array from node input "connections" / "links" fields
3. Auto-positions nodes in a vertical grid (input at top, output at bottom)
4. Preserves all class_type, inputs (widget values), and connection topology
"""
from __future__ import annotations

import json
import math
import sys
import uuid
from pathlib import Path
from typing import Any


# ----------------------------------------------------------- node positioning
COL_W = 320  # column width
ROW_H = 220  # row height
MARGIN_X = 80
MARGIN_Y = 60


def _grid_pos(index: int, total_cols: int = 4) -> list[float]:
    """Simple grid layout: left-to-right, top-to-bottom."""
    col = index % total_cols
    row = index // total_cols
    return [float(MARGIN_X + col * COL_W), float(MARGIN_Y + row * ROW_H)]


# ----------------------------------------------------------- topological sort
def _topo_sort(api_nodes: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Sort nodes so inputs come before outputs (Kahn's algorithm)."""
    node_ids = {nid for nid, _ in api_nodes}
    # Build adjacency: node_id -> set of node_ids it depends on
    deps: dict[str, set[str]] = {nid: set() for nid, _ in api_nodes}
    for nid, ndata in api_nodes:
        for key, val in ndata.get("inputs", {}).items():
            if isinstance(val, list) and len(val) >= 2 and str(val[0]) in node_ids:
                deps[nid].add(str(val[0]))
    # Kahn's algorithm
    result: list[tuple[str, dict]] = []
    completed: set[str] = set()
    remaining = list(api_nodes)
    while remaining:
        progressed = False
        still: list[tuple[str, dict]] = []
        for nid, ndata in remaining:
            if deps[nid] <= completed:
                result.append((nid, ndata))
                completed.add(nid)
                progressed = True
            else:
                still.append((nid, ndata))
        remaining = still
        if not progressed:
            # Circular dep or dangling ref — append remaining in original order
            result.extend(remaining)
            break
    return result


# ----------------------------------------------------------- conversion
def convert_api_to_ui(api_data: dict[str, Any]) -> dict[str, Any]:
    """Convert a single API-format workflow dict to UI format."""
    # Collect nodes (keys that are digit strings = node IDs)
    raw_nodes: list[tuple[str, dict]] = []
    for key, val in api_data.items():
        if key.isdigit() and isinstance(val, dict):
            raw_nodes.append((key, val))
    # Sort topologically so positions flow naturally
    raw_nodes = _topo_sort(raw_nodes)

    # First pass: assign node IDs and collect output types
    node_id_map: dict[str, int] = {}
    for idx, (nid, _) in enumerate(raw_nodes):
        node_id_map[nid] = int(nid)  # keep original ID

    # Second pass: build links array
    # UI link format: [link_id, source_node, source_slot, target_node, target_slot, type]
    links: list[list[Any]] = []
    link_id_counter = 1

    # Track output slot usage per node (node_id -> next free slot)
    output_slots: dict[int, int] = {}
    # Track output links per node (node_id -> list of link_ids)
    output_links: dict[int, list[int]] = {int(nid): [] for nid, _ in raw_nodes}

    # First, build a map of outputs: (source_node_id, output_index) -> link_id
    # We need to collect all input connections first to know how many outputs each node has
    node_inputs: list[tuple[int, dict, list[tuple[int, int, str]]]] = []
    for nid, ndata in raw_nodes:
        int_nid = int(nid)
        input_conns: list[tuple[int, int, str]] = []
        for _key, val in ndata.get("inputs", {}).items():
            if isinstance(val, list) and len(val) >= 2:
                src_id = str(val[0])
                src_slot = int(val[1]) if len(val) > 1 else 0
                # Type from the connection if available, else generic
                conn_type = val[2] if len(val) > 2 and isinstance(val[2], str) else "*"
                if src_id in {n for n, _ in raw_nodes}:
                    input_conns.append((int(src_id), src_slot, conn_type))
        node_inputs.append((int_nid, ndata, input_conns))

    # Build links by iterating node inputs
    for int_nid, ndata, input_conns in node_inputs:
        node_inputs_ui: list[dict[str, Any]] = []
        for inp_idx, (src_nid, src_slot, conn_type) in enumerate(input_conns):
            link_id = link_id_counter
            link_id_counter += 1
            links.append([link_id, src_nid, src_slot, int_nid, inp_idx, conn_type])
            output_links.setdefault(src_nid, []).append(link_id)
            node_inputs_ui.append({
                "name": f"input_{inp_idx}",
                "type": conn_type,
                "link": link_id,
                "label": None,
                "shape": None,
                "dir": None,
                "pos": None,
                "color_on": None,
                "color_off": None,
                "removable": None,
                "nameLocked": None,
                "locked": None,
                "slot_index": inp_idx,
            })

        # Store the UI inputs back on the node
        ndata["_ui_inputs"] = node_inputs_ui

    # Third pass: build UI node objects with outputs
    ui_nodes: list[dict[str, Any]] = []
    for idx, (nid, ndata) in enumerate(raw_nodes):
        int_nid = int(nid)
        class_type = ndata.get("class_type", "Unknown")
        inputs = ndata.get("inputs", {})

        # Separate widget inputs (scalars) from connection inputs
        widget_values: list[Any] = []
        widget_keys: list[str] = []
        for key, val in inputs.items():
            if not (isinstance(val, list) and len(val) >= 2 and str(val[0]).isdigit()):
                widget_values.append(val)
                widget_keys.append(key)

        # Build outputs: one output per unique (source_node, slot) that is referenced
        # Count how many output slots this node has based on connections FROM it
        max_output_slot = 0
        for lid, snid, sslot, tnode, tslot, ctype in links:
            if snid == int_nid:
                max_output_slot = max(max_output_slot, sslot)
        num_outputs = max_output_slot + 1

        # Gather outgoing links for each output slot
        outputs_ui: list[dict[str, Any]] = []
        for slot in range(num_outputs):
            outgoing = [lid for lid, snid, sslot, _, _, _ in links if snid == int_nid and sslot == slot]
            outputs_ui.append({
                "name": "OUTPUT" if num_outputs == 1 else f"output_{slot}",
                "type": "*",
                "links": outgoing,
                "label": None,
                "shape": None,
                "dir": None,
                "pos": None,
                "color_on": None,
                "color_off": None,
                "removable": None,
                "nameLocked": None,
                "locked": None,
                "slot_index": slot,
            })

        # Use stored UI inputs if any, else empty
        ui_inputs = ndata.get("_ui_inputs", [])

        ui_node: dict[str, Any] = {
            "id": int_nid,
            "type": class_type,
            "pos": _grid_pos(idx),
            "size": {"width": 230, "height": 130},
            "mode": 0,
            "inputs": ui_inputs,
            "outputs": outputs_ui,
            "properties": {
                "ver": "0.25.0",
                "cnr_id": "comfy-core",
                "Node name for S&R": class_type,
            },
            "widgets_values": widget_values,
            "flags": {"collapsed": False},
            "order": idx,
        }
        ui_nodes.append(ui_node)

    # Remove temp key
    for _, ndata in raw_nodes:
        ndata.pop("_ui_inputs", None)

    return {
        "id": str(uuid.uuid4()),
        "revision": 0,
        "version": 0.4,
        "last_link_id": link_id_counter - 1,
        "nodes": ui_nodes,
        "links": links,
        "config": {},
        "groups": [],
        "extra": {},
        "definitions": {},
    }


# ----------------------------------------------------------- CLI
def _tidy_filename(name: str) -> str:
    return name.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_")


def convert_file(input_path: Path, output_path: Path | None = None) -> None:
    """Convert a single API-format file to UI format."""
    if output_path is None:
        # .api.json -> .json, or .json -> .ui.json
        stem = input_path.stem
        output_path = input_path.parent / f"{stem}.json"
    api_data = json.loads(input_path.read_text())
    # Skip if already UI format
    if "nodes" in api_data and "links" in api_data and isinstance(api_data.get("nodes"), list):
        print(f"SKIP  {input_path.name}  (already UI format)")
        return
    ui_data = convert_api_to_ui(api_data)
    output_path.write_text(json.dumps(ui_data, indent=2))
    n_nodes = len(ui_data["nodes"])
    n_links = len(ui_data["links"])
    print(f"OK    {input_path.name}  ->  {output_path.name}  ({n_nodes} nodes, {n_links} links)")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--all":
        if len(args) < 2:
            print("Error: --all requires a directory path")
            return 1
        directory = Path(args[1])
        if not directory.is_dir():
            print(f"Error: {directory} is not a directory")
            return 1
        count = 0
        for json_file in sorted(directory.glob("*.json")):
            if json_file.name.startswith("."):
                continue
            convert_file(json_file)
            count += 1
        print(f"\nConverted {count} file(s)")
        return 0
    # Single file mode
    input_path = Path(args[0])
    if not input_path.is_file():
        print(f"Error: {input_path} not found")
        return 1
    output_path = Path(args[1]) if len(args) > 1 else None
    convert_file(input_path, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
