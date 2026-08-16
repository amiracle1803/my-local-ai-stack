import json, glob, os, re
from PIL import Image

WF = os.path.expanduser("~/my-local-ai-stack/olympus/engines/pipeline/workflows")
INPUT = os.path.expanduser("~/my-local-ai-stack/ComfyUI/input")
os.makedirs(INPUT, exist_ok=True)

# collect every PATCH_*.png referenced by any LoadImage-style node
names = set()
for p in glob.glob(WF + "/*.json"):
    raw = open(p).read()
    for m in re.findall(r"PATCH_[A-Z_]+\.png", raw):
        names.add(m)

# neutral mid-gray 832x704 (panel size); masks want black, so make mask names black
for n in sorted(names):
    color = (0, 0, 0) if "MASK" in n else (128, 128, 128)
    Image.new("RGB", (832, 704), color).save(os.path.join(INPUT, n))
    print("wrote", n, color)
print(f"\n{len(names)} placeholder input images created")
