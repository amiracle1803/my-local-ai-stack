"""Convert Aether pipeline API-format workflows to ComfyUI UI-format graphs
with computed layouts, so every node renders on the canvas. Also emits one
master workflow combining all templates in labeled groups.

Ported into the repo 2026-07-09 (WF-1): object_info is fetched live from the
running ComfyUI at :8188, UI graphs are written to the C: primary install
(C:\\AI\\ComfyUI, never the E: mirror), and the two new templates
(wan_ti2v, lora_dataset_prep) are included."""

import json
import urllib.request
from pathlib import Path

# Paths resolve from this file so the tool runs on both Windows and Linux
# (2026-07-10: ComfyUI lives repo-local at ./ComfyUI on the Linux box).
WF = Path(__file__).resolve().parent.parent / "workflows"
REPO = WF.parents[3]
COMFY_URL = "http://127.0.0.1:8188"
OBJ = json.load(urllib.request.urlopen(COMFY_URL + "/object_info", timeout=60))
OUT_COMFY = REPO / "ComfyUI/user/default/workflows/aether-pipeline"
OUT_REPO = WF / "ui"

CONNECTION_TYPES = {"MODEL", "CLIP", "VAE", "CONDITIONING", "LATENT", "IMAGE",
                    "MASK", "IPADAPTER", "SIGMAS", "SAMPLER", "NOISE", "GUIDER"}
TEMPLATES = ["scene_plate", "panel_txt2img", "panel_img2img_lastframe",
             "character_sheet", "mouth_sheet", "ltx_ambient", "ltx_director",
             "wan_ti2v", "lora_dataset_prep", "image_flux_fallback",
             "image_krea2"]

NODE_W, NODE_H_BASE, COL_GAP, ROW_GAP = 340, 90, 420, 60


def node_schema(cls):
    s = OBJ[cls]["input"]
    fields = []  # (name, kind) kind: 'conn'|'widget'
    for section in ("required", "optional"):
        for name, spec in s.get(section, {}).items():
            t = spec[0]
            if isinstance(t, str) and t in CONNECTION_TYPES:
                fields.append((name, "conn", t))
            else:
                fields.append((name, "widget", t))
    outs = list(zip(OBJ[cls]["output"], OBJ[cls].get("output_name") or OBJ[cls]["output"]))
    return fields, outs


def convert(api, x0=0, y0=0, id_off=0, link_off=0):
    """Return (nodes, links, w, h) in UI format with a left-to-right layout."""
    # topological depth
    depth = {}
    def calc(nid):
        if nid in depth:
            return depth[nid]
        d = 0
        for v in api[nid]["inputs"].values():
            if isinstance(v, list):
                d = max(d, calc(str(v[0])) + 1)
        depth[nid] = d
        return d
    for nid in api:
        calc(nid)
    cols = {}
    for nid, d in sorted(depth.items(), key=lambda kv: (kv[1], int(kv[0]))):
        cols.setdefault(d, []).append(nid)

    ui_nodes, ui_links = [], []
    pos, link_id = {}, link_off
    # per-node link bookkeeping
    incoming = {nid: {} for nid in api}  # input_name -> link id
    outgoing = {nid: {} for nid in api}  # slot -> [link ids]

    # first pass: create links
    for nid, node in api.items():
        for iname, v in node["inputs"].items():
            if isinstance(v, list):
                link_id += 1
                src, slot = str(v[0]), v[1]
                incoming[nid][iname] = link_id
                outgoing[src].setdefault(slot, []).append(link_id)
                fields, _ = node_schema(node["class_type"])
                ftype = next((t for n, k, t in fields if n == iname), "*")
                ui_links.append([link_id, int(src) + id_off, slot, int(nid) + id_off,
                                 None, ftype])  # to_slot fixed in pass 2

    maxh = 0
    for d, nids in cols.items():
        y = y0
        for nid in nids:
            node = api[nid]
            cls = node["class_type"]
            fields, outs = node_schema(cls)
            ins, widgets = [], []
            conn_slot = 0
            for name, kind, t in fields:
                if kind == "conn":
                    lk = incoming[nid].get(name)
                    ins.append({"name": name, "type": t, "link": lk})
                    if lk:
                        for L in ui_links:
                            if L[0] == lk and L[3] == int(nid) + id_off and L[4] is None:
                                L[4] = conn_slot
                                break
                    conn_slot += 1
                else:
                    if name in node["inputs"] and not isinstance(node["inputs"][name], list):
                        widgets.append(node["inputs"][name])
                    else:
                        widgets.append(0)
                    if name in ("seed", "noise_seed"):
                        widgets.append("fixed")
            outs_ui = []
            for slot, (t, oname) in enumerate(outs):
                outs_ui.append({"name": oname, "type": t,
                                 "links": outgoing[nid].get(slot, []) or None,
                                 "slot_index": slot})
            n_widgets = len([1 for _, k, _ in fields if k == "widget"])
            h = NODE_H_BASE + 26 * (len(ins) + len(outs_ui)) + 28 * n_widgets
            px, py = x0 + d * COL_GAP, y
            pos[nid] = (px, py)
            ui_nodes.append({
                "id": int(nid) + id_off, "type": cls, "pos": [px, py],
                "size": [NODE_W, h], "flags": {}, "order": d, "mode": 0,
                "title": node.get("_meta", {}).get("title", cls),
                "inputs": ins, "outputs": outs_ui,
                "properties": {"Node name for S&R": cls},
                "widgets_values": widgets,
            })
            y += h + ROW_GAP
            # _meta.note -> a visible yellow Note card under the node so the
            # explanation reads on the canvas, not just in the API JSON.
            note = node.get("_meta", {}).get("note")
            if note:
                nh = 70 + 16 * (len(note) // 45)
                ui_nodes.append({
                    "id": int(nid) + id_off + 1000, "type": "Note",
                    "pos": [px, y], "size": [NODE_W, nh], "flags": {},
                    "order": d, "mode": 0, "title": f"note: {node['_meta'].get('title', cls)}",
                    "properties": {}, "widgets_values": [note],
                    "color": "#432", "bgcolor": "#653",
                })
                y += nh + ROW_GAP
            maxh = max(maxh, y - y0)
    width = (max(depth.values()) + 1) * COL_GAP
    return ui_nodes, ui_links, width, maxh


def emit(nodes, links, groups, path):
    doc = {
        "last_node_id": max(n["id"] for n in nodes),
        "last_link_id": max([l[0] for l in links] + [0]),
        "nodes": nodes, "links": links, "groups": groups,
        "config": {}, "extra": {}, "version": 0.4,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print("wrote", path)


def _installed(api, name):
    missing = {n["class_type"] for n in api.values() if n["class_type"] not in OBJ}
    if missing:
        print(f"skip {name}: node pack(s) not installed for {sorted(missing)}")
    return not missing


def main():
    # individual UI workflows
    for name in TEMPLATES:
        api = json.load(open(WF / f"{name}.json", encoding="utf-8"))
        if not _installed(api, name):
            continue
        nodes, links, w, h = convert(api)
        for target in (OUT_COMFY / f"{name}.json", OUT_REPO / f"{name}.ui.json"):
            emit(nodes, links, [], target)

    # master canvas: all templates stacked vertically in labeled groups
    all_nodes, all_links, groups = [], [], []
    y_cursor, id_off, link_off = 0, 0, 0
    for name in TEMPLATES:
        api = json.load(open(WF / f"{name}.json", encoding="utf-8"))
        if not _installed(api, name):
            continue
        nodes, links, w, h = convert(api, x0=60, y0=y_cursor + 80,
                                     id_off=id_off, link_off=link_off)
        all_nodes += nodes
        all_links += links
        groups.append({"title": f"AETHER · {name.upper()}",
                        "bounding": [20, y_cursor, w + 120, h + 140],
                        "color": "#2a363b", "font_size": 24, "flags": {}})
        y_cursor += h + 220
        id_off = max(n["id"] for n in all_nodes) + 10
        link_off = max([l[0] for l in all_links] + [0]) + 10
    emit(all_nodes, all_links, groups, OUT_COMFY / "aether-MASTER-all-stages.json")
    emit(all_nodes, all_links, groups, OUT_REPO / "aether-master.ui.json")


main()
