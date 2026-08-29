"""Generic Report: dataset → evidence Markdown."""

import os
from mio_cua.workflow.state import WorkflowState


def generate_report(state: WorkflowState, output: str) -> str:
    """Generate evidence Markdown report. Returns path."""
    state.assert_can_complete()
    lines = [f"# 监测报告（app={state.app}, keyword={state.keyword})", ""]
    lines.append("## 扫描摘要")
    lines.append(f"|候选|{len(state.candidates)}|已选|{len(state.selected_ids)}|消息数|{len(state.dataset)}|状态|{state.validation.get('status','')}|")
    lines.append("")
    if state.validation and state.validation.get("issues"):
        lines.append("## 异常")
        for iss in state.validation["issues"]:
            lines.append(f"- {iss}")
        lines.append("")
    lines.append("## 消息")
    for r in state.dataset:
        ts = f"[{r.timestamp}] " if r.timestamp else ""
        sender = f"{r.sender}: " if r.sender else ""
        lines.append(f"{ts}{sender}{r.content}")
        # provenance
        src = r.source or {}
        if src.get("screenshot"):
            lines.append(f"  <!-- source: {src.get('screenshot')} obs:{src.get('observation_id')} method:{src.get('extraction_method')} -->")
    content = "\n".join(lines)
    os.makedirs(os.path.dirname(os.path.abspath(output)) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(content)
    return output
