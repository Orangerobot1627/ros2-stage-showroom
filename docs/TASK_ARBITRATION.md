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

## 配置

策略文件是 `config/action_policy.yaml`：

- `override.default_duration_sec`：未指定时间时的接管时长，默认 20 秒。
- `min_duration_sec` / `max_duration_sec`：限制模型可请求的时间范围。
- `auto_resume`：租约到期后是否自动恢复。
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

语言示例：

```text
蓝色机器人在这里等 20 秒，然后继续原来的导览。
绿色机器人先停 10 秒，之后继续送咖啡。
两个机器人暂停 30 秒。
让绿色机器人现在立即执行默认配送任务。
```

Qwen 只能生成上述白名单 action、目标机器人和时间，不能生成坐标、速度或 `cmd_vel`。
任务管理器会再次根据 YAML 校验，模型输出不能绕过策略。

## 与 Nav2/Open-RMF 的关系

Stage 阶段保留轻量级航点控制器，任务仲裁层只使用 `start/pause/resume/cancel` 高层命令。
接入 Nav2 后，将路线命令适配为 ROS 2 Action 与行为树即可，租约和默认任务策略可以保留。
进一步扩展到多楼层、多机器人队列和充电调度时，再把该层替换或连接到 Open-RMF。

当前仍不允许从任意位置直接前往任意坐标，因为 Stage 参考控制器没有全局规划器。这类
`go_to_place` action 应在 Nav2 代价地图和路径规划接入后开放。
