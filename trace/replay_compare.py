"""Replay Comparison: UIA-only vs UIA+OCR vs UIA+OCR+QualityGate

Loads existing trace, finds WeChat steps, and compares scene graph quality
across three modes. This validates whether the Perception fix actually helps.
"""

import json
import os
import sys
from pathlib import Path
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from mio_cua.evaluation.recorder import ObsFrame, Trace, TraceStore
from mio_cua.perception.quality import assess_quality, enhance_scene_with_fallback, QualityReport
from mio_cua.scene.graph import SceneGraph, SceneNode
from mio_cua.vision import ocr as ocr_module

# ── Load trace ──

store = TraceStore("trace")
trace = store.load("trace_1787466378.json")

print("=" * 70)
print("Replay Comparison: UIA-only vs UIA+OCR vs UIA+OCR+QualityGate")
print(f"Trace: {trace.trace_id}, {len(trace.entries)} steps")
print("=" * 70)

# ── Find WeChat steps ──

wechat_steps = []
for i, entry in enumerate(trace.entries):
    obs = entry.obs_before
    if obs.active_window in ("微信", "WeChat"):
        wechat_steps.append((i, entry))

print(f"\nWeChat steps: {[s[0] for s in wechat_steps]}")

# ── Build scene graphs from trace nodes ──

def build_scene_from_nodes(nodes_data, window="微信"):
    """Build SceneGraph from trace node data."""
    scene = SceneGraph(active_window=window)
    for nd in nodes_data:
        node = SceneNode(
            id=nd.get("id", 0),
            type=nd.get("type", "unknown"),
            bbox=tuple(nd.get("bbox", [0, 0, 0, 0])),
            text=nd.get("text", ""),
            semantic=nd.get("semantic", ""),
        )
        scene.nodes.append(node)
    return scene

# ── Run comparison for each WeChat step ──

results = []

for step_idx, entry in wechat_steps:
    obs = entry.obs_before
    nodes_data = obs.scene_nodes
    screenshot_path = obs.screenshot_path

    print(f"\n{'─' * 70}")
    print(f"Step {step_idx}: active_window={obs.active_window!r}")
    print(f"  Screenshot: {screenshot_path}")

    # ── Mode 1: UIA-only (from trace) ──
    scene_uia = build_scene_from_nodes(nodes_data)
    q_uia = assess_quality(scene_uia)

    print(f"\n  [UIA-only]")
    print(f"    nodes:            {q_uia.node_count}")
    print(f"    interactive:      {q_uia.interactive_count}")
    print(f"    containers:       {q_uia.container_count}")
    print(f"    search_box:       {q_uia.has_search_box}")
    print(f"    usable:           {q_uia.is_usable}")
    print(f"    reason:           {q_uia.reason}")

    # ── Mode 2: UIA + OCR (run OCR on screenshot) ──
    ocr_nodes = []
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            import numpy as np
            img = Image.open(screenshot_path)
            img_array = np.array(img)
            ocr_elements = ocr_module.get_elements(img_array)
            for elem in ocr_elements:
                ocr_nodes.append({
                    "id": getattr(elem, "id", 0),
                    "type": "text",
                    "text": getattr(elem, "text", ""),
                    "bbox": getattr(elem, "bbox", (0, 0, 0, 0)),
                    "semantic": "ocr_detected",
                })
        except Exception as e:
            print(f"    OCR failed: {e}")

    # Merge UIA + OCR nodes
    merged_nodes = list(nodes_data)  # copy UIA
    for on in ocr_nodes:
        # Avoid duplicates by checking text overlap
        text = on.get("text", "")
        if text and not any(text in n.get("text", "") for n in merged_nodes):
            merged_nodes.append(on)

    scene_merged = build_scene_from_nodes(merged_nodes)
    q_merged = assess_quality(scene_merged)

    print(f"\n  [UIA + OCR]")
    print(f"    OCR nodes found:  {len(ocr_nodes)}")
    print(f"    merged nodes:     {q_merged.node_count}")
    print(f"    interactive:      {q_merged.interactive_count}")
    print(f"    search_box:       {q_merged.has_search_box}")
    print(f"    usable:           {q_merged.is_usable}")
    print(f"    reason:           {q_merged.reason}")

    # Show OCR text samples
    if ocr_nodes:
        texts = [n["text"] for n in ocr_nodes if n.get("text")][:8]
        print(f"    OCR texts:        {texts}")

    # ── Mode 3: UIA + OCR + QualityGate + Fallback ──
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            import numpy as np
            img = Image.open(screenshot_path)
            img_array = np.array(img)
            rect = (0, 0, img.width, img.height)
            scene_enhanced = build_scene_from_nodes(merged_nodes)
            scene_enhanced = enhance_scene_with_fallback(scene_enhanced, img_array, rect)
            q_enhanced = assess_quality(scene_enhanced)

            print(f"\n  [UIA + OCR + Fallback]")
            print(f"    total nodes:      {q_enhanced.node_count}")
            print(f"    interactive:      {q_enhanced.interactive_count}")
            print(f"    search_box:       {q_enhanced.has_search_box}")
            print(f"    usable:           {q_enhanced.is_usable}")
            print(f"    reason:           {q_enhanced.reason}")

            # Check target visibility
            target_found = False
            for n in scene_enhanced.nodes:
                if "兴蓉" in (n.text or ""):
                    target_found = True
                    print(f"    TARGET FOUND:     node id={n.id} text={n.text!r}")
            if not target_found:
                print(f"    target visible:   False")
        except Exception as e:
            print(f"    Fallback failed: {e}")
    else:
        print(f"\n  [Fallback] — no screenshot available")

    # ── Collect metrics ──
    target_in_uia = any("兴蓉" in (n.get("text", "") or "") for n in nodes_data)
    target_in_merged = any("兴蓉" in (n.get("text", "") or "") for n in merged_nodes)

    results.append({
        "step": step_idx,
        "uia_nodes": q_uia.node_count,
        "uia_interactive": q_uia.interactive_count,
        "uia_usable": q_uia.is_usable,
        "ocr_nodes": len(ocr_nodes),
        "merged_nodes": q_merged.node_count,
        "merged_interactive": q_merged.interactive_count,
        "merged_usable": q_merged.is_usable,
        "target_in_uia": target_in_uia,
        "target_in_merged": target_in_merged,
    })

# ── Summary ──

print(f"\n{'=' * 70}")
print("COMPARISON SUMMARY")
print(f"{'=' * 70}")
print(f"{'Step':>5} {'UIA':>5} {'OCR':>5} {'Merged':>7} {'Target':>8}")
for r in results:
    print(f"{r['step']:>5} {r['uia_nodes']:>5} {r['ocr_nodes']:>5} {r['merged_nodes']:>7} "
          f"{'YES' if r['target_in_merged'] else 'no':>8}")

# ── Save comparison report ──

report = {
    "trace_id": trace.trace_id,
    "comparison": results,
    "conclusion": "",
}

uia_usable = sum(1 for r in results if r["uia_usable"])
merged_usable = sum(1 for r in results if r["merged_usable"])
target_found = sum(1 for r in results if r["target_in_merged"])

report["conclusion"] = (
    f"UIA-only usable: {uia_usable}/{len(results)}. "
    f"UIA+OCR usable: {merged_usable}/{len(results)}. "
    f"Target visible after fallback: {target_found}/{len(results)}."
)

print(f"\n{report['conclusion']}")

with open("trace/replay_comparison.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"\nReport saved: trace/replay_comparison.json")
