# Architecture

`demo_stage` 提供仿真环境、机器人模型、参考路线执行器和第一版业务状态机。业务层
只处理结构化意图、状态和任务事件，不读取 Stage 模型，也不直接发布速度指令。

```text
visitor speech ──► PipeWire + ASR
                         │ /showroom/user_text
visitor text ────────────┤
        ▼
showroom LLM bridge ─────► /showroom/assistant_text
                                      │
                                      ▼
                               Piper TTS ──► speaker
        │ validated /showroom/command
        ▼
showroom task manager
        │ action policy + renewable human override lease
        │ plan executor + /showroom/navigation_requests
        ▼
semantic navigation gateway
        │ Stage optimized path or Nav2 plan
        ▼
reference waypoint followers ─────► /showroom/robot_events
        │                                   │
        │ /robot_N/cmd_vel                  └── state feedback
        ▼
stage_ros2 bridge ──► /robot_N/{odom,base_scan,ground_truth}
        │
        ▼
Stage world/models
```

`showroom_monitor` 订阅业务状态、路线事件、位姿、速度和激光雷达，将可观测性信息汇总到
`/showroom/monitor`。该节点只观察，不参与速度控制；删除或重启监控节点不会改变机器人的
导航行为。

`showroom_llm_bridge` 通过 HTTP 调用 Windows 宿主机上的本地模型。HTTP 请求放在后台
线程中，避免模型推理阻塞 ROS executor。桥接层只把 `start_tour`、`pause_tour` 等白名单
意图发布给任务管理器；状态询问和普通聊天不会形成运动命令。模型没有速度 Topic 的发布
器，因此即使模型输出异常，也不能绕过任务管理器直接控制底盘。

任务管理器加载 `config/action_policy.yaml`。默认导览和咖啡配送是低优先级基础任务；
人工 `robot_action` 可以临时暂停任意一台或两台机器人。租约默认持续 20 秒并使用单调
墙上时钟计时，新指令可以续期，`resume` 可以提前释放。租约结束后，任务管理器检查
暂停前业务状态并发布 `resume`，航点跟随器继续使用未被清除的当前索引。详细协议见
`docs/TASK_ARBITRATION.md`。

导览路线同时由 `showroom_task_units.py` 映射为语义任务单元。游客的跳过、重复和追问
针对任务单元执行，不直接操作坐标或任意航点索引。这一层也是后续 multi-step plan
executor 使用的稳定任务接口。

多任务层使用最多 8 步的封闭 action 集合。`SequentialPlanExecutor` 保存步骤状态，并在
配送等异步步骤上等待带同一 `mission_id` 的机器人事件。导航网关从业务层接收命名任务
地点，在 `navigation_graph.yaml` 上计算最短路径；当前 Stage 后端执行动态航点，Nav2
适配器可把同一计划转换为 `NavigateThroughPoses`。具体协议和参考项目见
`docs/MULTI_TASK_PLANNING.md`。

LLM 层内部继续按职责拆分：`showroom_ollama_client` 只处理 HTTP 和
`message.content`，`showroom_llm_prompt` 负责提示词与状态裁剪，
`showroom_llm_contract` 负责 JSON 解析、意图白名单和业务命令转换，ROS bridge 只连接
这些模块与现有 Topic。当前任务讲解始终由 `task_units.yaml` 中的 `summary` 或 `detail`
覆盖模型自由文本，避免小模型遗漏字段或编造展品。Ollama 的 `message.thinking` 不进入
输出协议解析。

后续 Nav2 接入时，用导航节点替换参考航点跟随器；Stage 世界和机器人传感器接口保持
不变。任务管理器继续使用命名地点和任务事件，LLM 不获得 `/cmd_vel` 控制权。

## Business state machine

任务管理器接受 JSON 结构化意图并维护两条状态链：

```text
guide:  IDLE -> RECEPTION -> TOURING -> GOING_TO_LOUNGE -> COMPLETED
coffee: STANDBY -> TO_PICKUP -> PICKUP -> DELIVERING -> DELIVERED
        -> RETURNING -> RETURNED
```

导览机器人到达 `tunnel_center_south` 时触发咖啡路线。这个位置由集成测试确定：更晚
触发会使两台机器人同时进入休息区的共享通道并互相阻挡。任务管理器还处理暂停、
恢复、取消、雷达阻塞和障碍清除事件。业务模式中的 `start` 和 `resume` 命令立即生效；
航点跟随器的 `start_delay_sec` 只服务于不经过任务管理器的定时演示，不能在航点事件
之后再增加一层延时。

当前 JSON 话题是用于快速验证 LLM 边界的原型。迁移到 Gazebo/Nav2 时，应把路线执行
命令替换为自定义 Action 或 `nav2_msgs/action/NavigateToPose` 适配层，业务状态机保持
不变。

参考控制器的航点使用展馆 `world` 绝对坐标，因此在 Stage 演示中订阅
`/robot_N/ground_truth`。`/robot_N/odom` 的原点是机器人各自的出生位置，不能直接与
这些绝对航点相减。正式导航应通过 TF 获取 `map -> base_link`，不依赖 ground truth。

直接使用 launch 时，Stage 和两个参考控制器默认放入 ROS Domain 81，并使用本机发现
范围。日常调试通过 `showroom_session` 启动器运行，由它从 81..99 中轮换分配空闲
Domain。调试命令通过同一工具执行或导入当前会话环境，避免终端连到另一场仿真。

## Simulation session isolation

ROS Domain 是通信层隔离边界，`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 只把发现
限制在当前电脑，不能隔离本机的两场仿真。因此会话管理器组合使用以下机制：

1. 每次启动轮换 Domain，连续两次调试不会默认复用同一频道。
2. 分配前使用不经过 ROS daemon 的图发现检查；检测到旧节点就跳过该 Domain。
3. 对 Domain 持有进程级文件锁，两个并发启动器不能选中同一频道。
4. 保存会话 ID、Domain、PID 和 Linux 进程启动标识，避免 PID 被复用后误操作。
5. launch 在独立进程组中运行；停止会话时先发送 SIGINT，超时后升级为 SIGTERM 和
   SIGKILL，降低 Stage 或控制节点残留的概率。
6. Stage 进程退出会触发 launch 全局关闭，防止关闭 GUI 后只剩控制节点继续运行。

运行状态放在用户私有的运行时目录，不属于项目配置，也不会进入版本控制。这个机制
管理由 `showroom_session` 启动的本机开发仿真；直接手工运行的节点仍会在分配前通过
ROS 图发现被识别为频道占用。

## Coordinate system

- Stage world frame: `world`
- Map size: 50.0 m x 35.0 m
- Resolution: 0.05 m/cell
- Origin: `[-25.0, -17.5, 0.0]`
- Positive X: right/east
- Positive Y: top/north
- Main entrance: south/bottom

## Stage models

`robot_0` is the guide robot and `robot_1` is the coffee-delivery robot. Both are
differential-drive bases with collision geometry, noisy wheel odometry and one
270-degree planar LiDAR. A single ranger is intentional: the Jazzy stage_ros2
bridge publishes it as `base_scan`; multiple rangers would be renamed
`base_scan1`, `base_scan2`, and so on.

Stage provides planar odometry and collision physics for these models. An IMU is
not fabricated because the current stage_ros2 bridge does not expose an IMU model.
It can be added later as a separate simulated ROS node if required.

## ROS interfaces

Because the world contains two position models, stage_ros2 prefixes each robot:

- `/robot_0/cmd_vel`, `/robot_0/odom`, `/robot_0/base_scan`
- `/robot_1/cmd_vel`, `/robot_1/odom`, `/robot_1/base_scan`
- `/robot_0/ground_truth`, `/robot_1/ground_truth`
- `/clock`, `/tf`, `/tf_static`
- `/reset_positions`

The default launch uses one common TF tree with prefixed frame IDs. This is useful
for showing both robots together and for later coordination.

## Asset generation

`tools/generate_showroom_assets.py` is the single source for the occupancy map,
route coordinates, Stage route markers, Nav2 metadata and preview. Re-run it after
changing geometry or waypoints; it also checks 0.42 m route clearance.
