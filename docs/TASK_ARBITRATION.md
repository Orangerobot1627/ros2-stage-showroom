# 默认任务与人工临时接管

## 目标

蓝色机器人默认执行展馆导览，绿色机器人默认执行咖啡配送。游客语言指令的优先级高于
默认任务，但临时指令不会永久夺走机器人控制权。没有新的人工任务时，租约到期后恢复
暂停前的路线和航点。

```text
默认任务（低优先级）
        │
        ├── 人工 action 到达 ──► 暂停并保存业务状态/航点
        │                              │
        │                        临时接管租约
        │                              │
        └──── 租约到期或 resume ◄─────┘
                      │
                      ▼
              从原航点继续默认任务
```

当前租约使用系统单调时钟，而不是 Stage 仿真时间。这样无界面仿真加速时，“等待 20 秒”
仍然是现实中的 20 秒。

`temporary_visit` 使用同一套优先级原则，但会保存更完整的主任务快照：剩余场馆、跳过
列表、当前任务和业务状态。机器人到达指定场馆后可停留 `dwell_sec`，到达、导航失败或
超过 `timeout_sec` 都会重新生成原导览计划。临时任务的航点事件不会改写主任务的
`current_task`。

## 配置

策略文件是 `config/action_policy.yaml`：

- `override.default_duration_sec`：未指定时间时的接管时长，默认 20 秒。
- `min_duration_sec` / `max_duration_sec`：限制模型可请求的时间范围。
- `auto_resume`：租约到期后是否自动恢复。
- `temporary_navigation.default_timeout_sec`：临时场馆导航的默认安全期限。
- `temporary_navigation.max_dwell_sec`：到达临时目的地后的最长停留时间。
- `robots.*.default_route`：每台机器人的默认任务路线。
- `robots.*.aliases`：自然语言和外部接口可以使用的机器人别名。
- `actions`：允许进入业务层的高层 action 白名单。

启动时可以临时覆盖默认时间：

```bash
override_timeout_sec:=30.0
```

也可以使用另一个策略文件：

```bash
action_policy_file:=/absolute/path/to/action_policy.yaml
```

## 当前 action

| action | 目标 | 行为 |
|---|---|---|
| `pause` | guide/coffee/all | 暂停并创建可续期租约 |
| `resume` | guide/coffee/all | 提前结束租约并恢复原任务 |
| `start_default` | guide/coffee | 启动该机器人的默认路线 |
| `cancel` | guide/coffee/all | 取消指定机器人的任务 |
| `temporary_visit` | guide | 临时前往命名展区，到达/超时后恢复原导览 |

语言示例：

```text
蓝色机器人在这里等 20 秒，然后继续原来的导览。
绿色机器人先停 10 秒，之后继续送咖啡。
两个机器人暂停 30 秒。
让绿色机器人现在立即执行默认配送任务。
带我去时空隧道停留20秒，然后继续原导览。
```

Qwen 只能生成上述白名单 action、目标机器人和时间，不能生成坐标、速度或 `cmd_vel`。
任务管理器会再次根据 YAML 校验，模型输出不能绕过策略。

## 与 Nav2/Open-RMF 的关系

Stage 阶段保留轻量级航点控制器。Nav2 配置已将命名场馆临时任务适配为 ROS 2
Action，租约和默认任务策略位于上层，不依赖具体控制器。接口只开放配置中的稳定场馆 ID，
不接受 LLM 自由生成坐标。扩展到多楼层、多机器人队列和充电调度时，再将该层替换或连接到
Open-RMF。
