# Phase 3 端到端演示报告

> 用 mock 替代真实桌面/微信，但 **AgentLoopV2 的真实编排逻辑全部执行**：
> 信念状态、目标可见性不变量、动作执行、失败截断、事件总线录制。

## 场景结果

- 成功场景：`SUCCESS`（steps=3）
- 失败场景：`FAIL`（steps=3）

## 录制 Trace（重新加载自磁盘）

### 成功场景
```
  trace_id=232877a5  事件数=17  成功=True  status=SUCCESS
  [ 0] task_started
  [ 0] observation
  [ 0] belief_updated
  [ 0] plan_created  -> click(1)
  [ 0] action_started
  [ 0] action_completed -> click  success=True
  [ 1] observation
  [ 1] belief_updated
  [ 1] plan_created  -> type(2)
  [ 1] action_started
  [ 1] action_completed -> type  success=True
  [ 2] observation
  [ 2] belief_updated
  [ 2] plan_created  -> success(编辑)
  [ 2] action_started
  [ 2] action_completed -> success  success=True
  [16] task_completed -> SUCCESS
```

### 失败场景
```
  trace_id=dd48d846  事件数=17  成功=False  status=FAIL
  [ 0] task_started
  [ 0] observation
  [ 0] belief_updated
  [ 0] plan_created  -> click(1)
  [ 0] action_started
  [ 0] action_completed -> click  success=True
  [ 1] observation
  [ 1] belief_updated
  [ 1] plan_created  -> type(2)
  [ 1] action_started
  [ 1] action_completed -> type  success=False
  [ 2] observation
  [ 2] belief_updated
  [ 2] plan_created  -> fail(编辑)
  [ 2] action_started
  [ 2] action_completed -> fail  success=True
  [16] task_failed -> FAIL
```

## 确定性重放

- 成功：`deterministic replay: 17 events, status=SUCCESS`
- 失败：`deterministic replay: 17 events, status=FAIL`（triggered_real_action=False，满足 AC3）

## 失败归因

- **category**: `perception`  **confidence**: `0.85`
- **reason**: Observation never detected the target and exposed no search affordance — Perception gap
- **evidence**: ['target_visible=False', 'search_box_present=False']

## 基准聚合（2 条 Trace）

- total_tasks=2 success=1 failed=1
- success_rate=0.5
- failure_distribution={'perception': 1}
- average_steps=17.0  step_success_rate=0.8333

## 产物位置

- 报告：E:\work\code\agent-dev\desktop-agent\phase3_demo\report.md
- 成功 Trace：E:\work\code\agent-dev\desktop-agent\phase3_demo\2026-08-26\232877a5/trace.jsonl
- 失败 Trace：E:\work\code\agent-dev\desktop-agent\phase3_demo\2026-08-26\dd48d846/trace.jsonl
