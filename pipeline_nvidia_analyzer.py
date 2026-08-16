#!/usr/bin/env python3
"""
Pipeline Issue Analyzer with NVIDIA Reasoning API Integration

Combines ComfyUI workflow review (stages 0-5) with NVIDIA API analysis
for pipeline bottlenecks, model compatibility, and VRAM optimization.
"""

import json
import requests
import os
import sys

# Configuration
invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"
API_KEY = "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"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
}

# Working engine configs (verified on 8GB VRAM)
VERIFIED_ENGINES = {
    "hunyuan": {
        "status": "VERIFIED_WORKING",
        "output": "848x480x53f webm (622KB)",
        "config": "tile_size: 256 in hunyuan_i2v.json; GGUF Q4_K_M; bf16 T5 on CPU",
    },
    "ltx_2b": {
        "status": "VERIFIED_WORKING",
        "output": "768x448x81f mp4 (116KB)",
        "config": "lowvram + cache-lru 10; .ltx_smoke_passed marker",
    },
    "wan_ti2v": {
        "status": "BLOCKED",
        "output": "Sampler 96vs48 channel mismatch at node 9",
        "config": "Model in_dim=48 vs always-96-input; no code fix within current graph",
    },
}


def nvidia_reasoning_analyze(prompt, context=""):
    """Query NVIDIA reasoning model for pipeline analysis."""
    payload = {
        "messages": [
            {
                "role": "system",
                "content": "Expert AI systems engineer. Analyze pipeline bottlenecks, model compatibility issues, VRAM optimization strategies. Provide concise, technical, actionable analysis under 300 words.",
            },
            {"role": "user", "content": f"{prompt}\n\nContext: {context}"},
        ],
        "model": "nvidia/nemotron-3-nano-omni-30b-a30b-reasoning",
        "max_tokens": 2048,
        "reasoning_budget": 1024,
        "stream": False,
        "temperature": 0.2,
        "top_p": 0.95,
    }
    try:
        r = requests.post(invoke_url, headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return f"API error {r.status_code}: {r.text}"
    except Exception as e:
        return f"API connection error: {e}"


def analyze_stage(stage_num, details=""):
    """Analyze a specific pipeline stage using NVIDIA API."""
    stage_titles = {
        "0": "Manifest & Template Validation",
        "1": "Template Loading & Patch Key Mapping",
        "2": "Model Loading & GPU Memory Management",
        "3": "Node Execution & VRAM Coordination",
        "4": "Post-Execution & Output Processing",
        "5": "Results Validation & Reporting",
    }
    title = stage_titles.get(stage_num, f"Stage {stage_num}")

    stage_prompts = {
        "0": "Manifest corruption fix analysis - manifest.json hunyani nesting repair, JSON validity, template load validation",
        "1": "Wan graph rebuild analysis - patch key mapping from manifest to node positions, node wiring correctness, 16 patch keys validation",
        "2": "GPU memory management and model selection for 8GB VRAM - GGUF Q4 vs fp8, VAE tile_size optimization, T5 fp8->bf16 switch, cache-lru interactions",
        "3": "Wan encode OOM then sampler channel mismatch analysis - fresh server restart to clear cache-lru, execute order (encode before model load), encode success vs sampler crash",
        "4": "96 vs 48 channel concat mismatch in WanVideoSampler with GGUF TI2V model - model in_dim=48 from conv weight vs sampler always producing 96 channels (48 noise + image_cond concat + additional); root cause is model-design vs graph-code mismatch",
        "5": "Pipeline completion status and verified working configurations - Hunyuan I2V + LTX 2B both verified on 8GB VRAM; Wan TI2V blocked; next steps documentation",
    }

    prompt = stage_prompts.get(stage_num, f"Stage {stage_num} analysis")
    full_context = f"{prompt}\n\nDetails: {details}"
    return nvidia_reasoning_analyze(prompt, full_context)


def engine_status_report():
    """Report verified engine statuses."""
    report = ["=" * 60, "VERIFIED ENGINE STATUS ON 8GB VRAM", "=" * 60]
    for name, info in VERIFIED_ENGINES.items():
        report.append(f"\n{name.upper()}: {info['status']}")
        report.append(f"  Output: {info['output']}")
        report.append(f"  Key Config: {info['config']}")
    report.append("\n" + "=" * 60)
    return "\n".join(report)


def workflow_stage_analysis(stage_num, details=""):
    """Convenience wrapper for stage analysis."""
    return analyze_stage(stage_num, details)


# --- Execute Analysis ---

if __name__ == "__main__":
    print("=" * 60)
    print("PIPELINE ISSUE ANALYZER + NVIDIA REASONING API")
    print("=" * 60)

    # 1. Engine status report
    print("\n" + "=" * 60)
    print("VERIFIED ENGINE STATUS")
    print("=" * 60)
    print(engine_status_report())

    # 2. Stage-by-stage analysis
    print("\n" + "=" * 60)
    print("PIPELINE STAGE ANALYSIS (NVIDIA Reasoning)")
    print("=" * 60)

    for stage in range(6):
        result = workflow_stage_analysis(stage, "")
        print(f"\n--- Stage {stage}: {['Manifest','Patch Keys','GPU Mem','Node Exec','Post-Exec','Results'][stage]} ---")
        print(f"  {result[:400]}...")

    # 3. Specific Wan blocker analysis
    print("\n" + "=" * 60)
    print("SPECIFIC ISSUE: Wan TI2V Sampler 96vs48 Mismatch")
    print("=" * 60)
    wan_issue = """WanVideoSampler node 9 fails: 'Given groups=1, weight of size [3072, 48, 1, 2, 2], expected input[1, 96, 21, 28, 48]'

Model: GGUF Q4_K_M Wan2.2-TI2V-5B (patch_embedding weight in_dim=48)
Sampler forward: concatenates noise(48) + image_cond(16 from encode) + additional embeddings = 96 channels
Root: Model designed for T2V+I2V dual 48-ch embeddings (total 96), but our graph path produces 96 unconditionally while weight expects 48"""

    print("\n" + nvidia_reasoning_analyze("", wan_issue))

    # 4. Summary recommendations
    print("\n" + "=" * 60)
    print("RECOMMENDATIONS")
    print("=" * 60)
    print("""
1. PRIMARY: Use Hunyuan I2V or LTX 2B for 8GB VRAM video generation - both VERIFIED
2. WAN TI2V: Document as blocked - model/graph in_dim mismatch; requires larger VRAM or different model
3. IMPORTED WORKFLOWS: 3 workflows copied to ~/.config/Comfline/user/custom_nodes/ComfyUI/workflows/
   - MiniMax-T2V-Reference.json (6 nodes, minimal T2V reference)
   - MiniMax-Image-Video-Turbo.json (28 nodes, 4-step turbo)
   - LTX-CloseUp-Shots-Reference.json (113 nodes, confirmed working LTX pattern)
4. NVIDIA API: Integrated for stage analysis and issue diagnosis as shown in this script
5. SERVER MANAGEMENT: Always --lowvram --cache-lru 10; restart comfyui-server.service between different engine runs
""")

    print("""
SCRIPT USAGE:
- Run: python pipeline_nvidia_analyzer.py
- Queries NVIDIA reasoning API for each pipeline stage
- Provides root cause analysis and fix recommendations
- Outputs verified engine status and stage-by-stage diagnostics
""")
