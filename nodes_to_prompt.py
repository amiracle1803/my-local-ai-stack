#!/usr/bin/env python3
"""
nodes_to_prompt.py
Convert a ComfyUI workflow (nodes[] format) to API prompt format.
Handles dtype normalization, image copying, optional inputs.
"""

import json
import shutil
from pathlib import Path

COMFY_INPUT_DIR = Path("/home/amire/Downloads/my-local-ai-stack/ComfyUI/input")

# value normalization: map invalid API values to valid ones
DTYPE_FIX = {
    "half": "bf16",
}

DEVICE_FIX = {
    "auto": "main_device",
}

def fix_value(input_name, val, input_type):
    if input_type == "IMAGEUPLOAD":
        return None  # skip
    if isinstance(val, str):
        if input_name in ("weight_dtype", "compute_dtype") and val in DTYPE_FIX:
            return DTYPE_FIX[val]
        if input_name == "device" and val in DEVICE_FIX:
            return DEVICE_FIX[val]
    return val

def copy_image_to_input(path):
    p = Path(path)
    if not p.exists():
        return None
    dst_name = f"mystic_eyes_{p.name}"
    dst = COMFY_INPUT_DIR / dst_name
    if not dst.exists():
        shutil.copy2(p, dst)
    return dst_name

def nodes_to_prompt(wf):
    nodes = wf.get('nodes', [])
    link_map = {}
    for node in nodes:
        nid = node['id']
        for out_idx, out in enumerate(node.get('outputs', [])):
            for link_id in out.get('links', []):
                link_map[link_id] = (nid, out_idx)
    prompt = {}
    for node in nodes:
        nid = node['id']
        klass = node['type']
        inputs = {}
        wvs = node.get('widgets_values')
        if isinstance(wvs, dict):
            def get_widget_val(inp_name, widget_info):
                wname = widget_info.get('name') if widget_info else inp_name
                return wvs_map.get(wname)
            wvs_map = wvs
        else:
            wvs_list = wvs if isinstance(wvs, list) else []
            w_idx = 0
            def get_widget_val(inp_name, widget_info):
                nonlocal w_idx
                if w_idx < len(wvs_list):
                    val = wvs_list[w_idx]
                    w_idx += 1
                    return val
                return None

        for inp in node.get('inputs', []):
            name = inp['name']
            link = inp.get('link')
            input_type = inp.get('type', '')
            if link is not None:
                src_nid, src_out_idx = link_map.get(link, (None, None))
                if src_nid is not None:
                    inputs[name] = [str(src_nid), src_out_idx]
                continue
            widget_info = inp.get('widget')
            if widget_info is None or input_type == "IMAGEUPLOAD":
                continue
            key = widget_info.get('name') or name
            val = get_widget_val(name, widget_info)
            val = fix_value(name, val, input_type)
            if val is None:
                continue
            # Rewrite image paths to ComfyUI/input filenames
            if klass == "LoadImage" and name == "image":
                val = copy_image_to_input(val) or val
            inputs[key] = val
        prompt[str(nid)] = {"class_type": klass, "inputs": inputs}
    return {"prompt": prompt}

if __name__ == "__main__":
    import sys
    wf = json.load(open(sys.argv[1]))
    out = nodes_to_prompt(wf)
    json.dump(out, open(sys.argv[2], 'w'), indent=2)