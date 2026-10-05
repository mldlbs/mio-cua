"""Re-classify existing trace with fuzzy window matching."""
import json
from mio_cua.evaluation.recorder import TraceStore
from mio_cua.evaluation.trace import FailureClassifier

store = TraceStore("trace")
trace = store.load("trace_1787466378.json")
fc = FailureClassifier()
results = fc.classify_trace(trace, "兴蓉", "WeChat")
summary = fc.summary(results)

print("Corrected classification (fuzzy window matching):")
print(f"  Total steps: {summary['total_steps']}")
print(f"  Perception:  {summary['perception_rate']:.0%}")
print(f"  Planner:     {summary['planner_rate']:.0%}")
print(f"  Action:      {summary['action_rate']:.0%}")
print(f"  Environment: {summary['environment_rate']:.0%}")
print()

for i, (entry, r) in enumerate(zip(trace.entries, results)):
    act = entry.action
    act_str = f"{act.type}({act.params})" if act else "None"
    status = r["category"] or "OK"
    print(f"  Step {i:2d}: [{status:20s}] {act_str[:60]}")
    if r["category"]:
        print(f"          {r['detail'][:80]}")
