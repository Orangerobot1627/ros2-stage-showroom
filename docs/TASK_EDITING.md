# Dynamic Task Editing

The fixed guide route is exposed as seven visitor-facing task units:

1. 入馆接待
2. 科技发展历史展区
3. 计算机视觉展厅
4. 智能机器人展厅
5. 时空科技隧道
6. 科技舞蹈展厅
7. 智能休息服务区

`config/task_units.yaml` maps every unit to a contiguous label range in
`config/routes.yaml`. The task manager resolves labels to indices at startup and
publishes the current unit as `business.current_task` on
`/showroom/monitor`. The LLM receives semantic state without coordinates.

## Supported intents

| Intent | Result |
|---|---|
| `skip_current` | Skip the current unit and seek to the next unit start |
| `repeat_current` | Seek back to the current unit start |
| `next_task` | Finish the current interaction and enter the next unit |
| `explain_current` | Speak a short explanation grounded in `summary` |
| `explain_more` | Speak a detailed follow-up grounded in `detail` |

The first three intents generate an internal `seek` route command. Only the
task manager calculates its validated waypoint index. The LLM cannot send a
coordinate, velocity, or arbitrary route index. Explanation intents do not
change motion.

## Data flow

```text
visitor text
  -> Qwen intent
  -> current-task summary/detail grounding
  -> showroom_llm_contract
  -> showroom_task_manager
  -> TaskUnitTracker
  -> internal route seek (editing intents only)
  -> waypoint_follower
```

Route events update the tracker again, so `current_task` remains aligned with
actual progress after normal motion, a repeat, or a skip. While a seek is
pending, the tracker ignores older waypoint and seek events; rapid consecutive
edits therefore cannot roll the semantic task back to a stale unit.

For explanation intents, the LLM classifies the request but the bridge replaces
its prose with the configured `summary` or `detail` of `current_task`. This keeps
spoken content grounded even when a small local model omits `reply` or invents
unsupported details.

## Manual tests

```bash
ros2 topic pub --once /showroom/user_text std_msgs/msg/String \
  "{data: '这个展厅没兴趣，跳过吧'}"

ros2 topic pub --once /showroom/user_text std_msgs/msg/String \
  "{data: '重新参观一下当前展区'}"

ros2 topic pub --once /showroom/user_text std_msgs/msg/String \
  "{data: '介绍一下当前展区'}"

ros2 topic pub --once /showroom/user_text std_msgs/msg/String \
  "{data: '再详细讲讲'}"
```

Inspect structured task state with:

```bash
ros2 topic echo /showroom/status --field data --full-length
```

Run the regression test with:

```bash
python3 tools/test_task_units.py
```
