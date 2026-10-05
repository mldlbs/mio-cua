"""Generic Validation: visual_compare / completeness_check."""

from mio_cua.workflow.state import WorkflowState


def validate(state: WorkflowState) -> dict:
    """Validate dataset completeness, never overwriting original artifact."""
    if not state.dataset:
        result = {"status": "failed", "issues": ["empty dataset"]}
    else:
        issues = []
        for r in state.dataset:
            if r.confidence < 0.85:
                issues.append(f"low confidence: {r.content[:20]!r}")
        # check for unexpanded indicator in any record
        for r in state.dataset:
            if "...and" in r.content or "more" in r.content.lower():
                issues.append("unexpanded list detected")
                break
        status = "failed" if issues else "passed"
        result = {"status": status, "issues": issues, "count": len(state.dataset)}
    # Validation failure must not overwrite original artifact -> store as new validation result
    state.set_validation(result)
    return result
