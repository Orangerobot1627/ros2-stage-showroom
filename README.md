# demo_stage

基于 ROS 2 Jazzy、Stage 和 `stage_ros2` 的科技展馆双机器人仿真项目。项目提供一个
50 m × 35 m 的单层展馆、两台差速机器人、可复用的占据栅格地图，以及用于验证路线
和传感器接口的轻量级航点跟随器。

当前版本提供稳定、可复现的 Stage 仿真底座、事件驱动的双机器人任务编排，以及可连接
Windows 本地模型服务的 LLM 桥接层。Nav2、语音和视觉能力将在此基础上继续接入。

## 功能

- 科技展馆：入口、中央咖啡区、科技历史展线、视觉馆、机器人馆、时空隧道、科技舞蹈区和休息区
- `robot_0`：导览机器人，差速底盘、里程计和 270° 二维激光雷达
- `robot_1`：咖啡配送机器人，差速底盘、托盘、里程计和 270° 二维激光雷达
- 导览路线：65 个航点，从入口依次经过各展区并到达休息区
- 配送路线：19 个航点，从待机区前往咖啡区和休息区，随后返回待机点
- 导览与咖啡配送状态机、结构化命令入口以及航点事件反馈
- 聚合运行监控：仿真时间、航点进度、位姿、速度、雷达净空、阻塞时长和恢复状态
- 根据导览进度派发咖啡任务，避免使用固定时间启动配送
- 配置驱动的机器人 action、人工临时接管租约和默认任务自动恢复
- 7 个语义导览任务单元，支持跳过、重复、进入下一任务和上下文讲解
- 受控多步骤计划、顺序执行状态机和小模型多意图修复
- 语义导航网关与 Dijkstra 路线优化，支持把饮料送到当前展区
- 可选 Nav2 `NavigateThroughPoses` 适配器，保持业务层与导航后端解耦
- 可选的本地 LLM 桥接层，支持 Qwen 的 Ollama 和 OpenAI 兼容 HTTP 接口
- 本地 Whisper 中文语音识别和 Piper 中文语音合成，支持半双工防回声
- 两台机器人共享全馆语义路网，支持任意展区饮料配送与服务专用最短路径
- 支持跳过指定场馆、只参观指定场馆，以及 Stage 雷达局部绕障和路线回归
- Stage GUI 路线标记、无界面运行模式和机器人位置重置服务
- 可供 Nav2 使用的占据栅格地图
- 不依赖 ROS 的地图、配置和路线净空校验工具

## 仓库结构

```text
demo_stage/
├── .github/workflows/validate.yml
├── config/                 # 地标、区域和路线配置
├── docs/                   # 架构说明
├── launch/                 # 基础仿真和自动演示启动文件
├── map/                    # Nav2 map_server 地图元数据
├── scripts/                # 参考航点跟随节点
├── tools/                  # 地图生成与静态校验工具
└── world/                  # Stage world、模型、路线标记和栅格地图
```

任务 action 与 20 秒临时接管机制见
[docs/TASK_ARBITRATION.md](docs/TASK_ARBITRATION.md)。主要参数位于
`config/action_policy.yaml`，可以配置默认路线、机器人别名、允许的 action、默认接管时间
以及最长/最短时间。

动态任务编辑见 [docs/TASK_EDITING.md](docs/TASK_EDITING.md)。任务边界和讲解资料位于
`config/task_units.yaml`；LLM 只选择受控 intent，实际航点索引由任务管理器解析和校验。

多任务与导航框架见
[docs/MULTI_TASK_PLANNING.md](docs/MULTI_TASK_PLANNING.md)。当前默认使用经过地图净空
校验的 Stage 图导航；Nav2 适配器已提供接口，但需要独立配置定位、TF、Costmap、Planner
和 Controller 后才能切换为实际 Nav2 控制。

## 环境要求

- Ubuntu 24.04
- ROS 2 Jazzy
- Stage
- `stage_ros2`
- Python 3 和 PyYAML

本工作区将 `Stage`、`stage_ros2` 和本包并列放在
`/home/xxl/ros2_ws/src/sim_stage/` 下。不要把 `demo_stage` 放进 `stage_ros2` 包内部。

## 构建

```bash
source /opt/ros/jazzy/setup.bash
cd /home/xxl/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-up-to demo_stage
source install/setup.bash
```

如果工作区曾经构建过另一份同名 `demo_stage`，请确保 `src` 中只保留一个可被
`colcon` 发现的版本。

## 运行

只启动 Stage、地图和两台机器人：

```bash
ros2 launch demo_stage showroom.launch.py
```

启动双机器人参考路线演示时，推荐使用会话管理器：

```bash
ros2 run demo_stage showroom_session start --monitor-windows
```

它会在安全池 `81..99` 中轮换选择空闲 ROS Domain，启动前通过 ROS 图检查频道是否
已有节点，并在仿真运行期间持有文件锁。`Ctrl+C` 会停止整个 launch 进程组。这样即使
上一次仿真没有正确退出，下一次也不会进入相同通信频道。

`--monitor-windows` 会先打开“中文监控”和“详细监控”两个终端，使订阅器先进入对应
Domain 等待，再启动 Stage。仿真结束后，这两个窗口会随本次会话退出。需要增加提前量时
可加 `--monitor-lead-sec 1.5`。

在另一个终端检查当前仿真，有两种方式。单条命令可以直接通过管理器执行：

```bash
ros2 run demo_stage showroom_session exec -- ros2 topic list
```

需要连续执行多条 ROS 命令时，把当前会话环境导入该终端：

```bash
eval "$(ros2 run demo_stage showroom_session env)"
ros2 node list
ros2 topic info /robot_0/cmd_vel -v
```

查看或停止当前会话：

```bash
ros2 run demo_stage showroom_session status
ros2 run demo_stage showroom_session business-status
ros2 run demo_stage showroom_session monitor
ros2 run demo_stage showroom_session detail-monitor
ros2 run demo_stage showroom_session stop
```

其中 `status` 检查 launch 进程和 Domain，`business-status` 显示导览与配送机器人的业务
状态，`monitor` 以 10 Hz 数据刷新中文运行看板，`detail-monitor` 以默认 5 Hz 显示完整
JSON。它们会自动加入当前会话，不需要先执行 `eval`。

在启动终端按 `Ctrl+C` 或关闭 Stage GUI 窗口也会关闭整场 launch；路线跟随节点不会
在 Stage 退出后单独留在后台。

会话状态保存在 `${XDG_RUNTIME_DIR:-/tmp}/demo_stage-$UID/`，不会写入仓库。自动分配器
同时采用四层保护：轮换 Domain、启动前发现检查、每个 Domain 的互斥锁以及整组进程
清理。发现范围固定为 `LOCALHOST`，避免同一局域网中其他电脑加入本机调试。

仍可直接使用标准 launch，主要用于显式复现实验：

```bash
ros2 launch demo_stage showroom_demo.launch.py ros_domain_id:=82
```

直接启动时不会获得自动分配、占用检查和进程组清理保护。CLI 终端必须手动设置与
launch 相同的 `ROS_DOMAIN_ID`。

无 GUI 运行：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py -- enable_gui:=false
```

Stage GUI 默认以 3 倍仿真速度运行，并为 VMware 启用 Mesa 软件渲染。如果运行在
支持稳定硬件 OpenGL 的实体机上，可以关闭软件渲染：

```bash
ros2 launch demo_stage showroom.launch.py software_rendering:=0
```

时间倍率在 `world/showroom_final.world` 的 `speedup` 字段中设置。无 GUI 模式不受该
字段限制，会尽可能快地运行。

不使用业务管理器、直接按时间启动两条路线：

```bash
ros2 launch demo_stage showroom.launch.py \
  auto_drive:=true business_mode:=false coffee_start_delay_sec:=380.0
```

推荐的 `showroom_demo.launch.py` 使用业务模式。导览机器人先执行参观路线；到达
`tunnel_center_south` 后，任务管理器向配送机器人发布任务，使其在导览机器人进入
休息区前完成取货和配送，并错开共享通道。业务模式收到航点事件后立即启动绿色
机器人，不再叠加 `coffee_start_delay_sec`；该延时参数只用于上面的非业务定时模式。

需要试验其他联动点时，可以直接使用路线中的航点标签：

```bash
ros2 run demo_stage showroom_session start -- \
  coffee_trigger:=history_panel_5
```

参考航点跟随器使用 `/robot_N/ground_truth`，因为 YAML 航点采用 `world` 绝对坐标，
而 Stage 的 `/robot_N/odom` 从每台机器人的出生位置重新以 `(0, 0)` 计数。该真值位姿
只用于 Stage 路线演示；接入 Nav2 后应由 AMCL、SLAM 或其他定位模块提供 `map` 坐标。

## ROS 2 接口

| 机器人 | 速度指令 | 里程计 | 激光雷达 | 真值位姿 |
|---|---|---|---|---|
| 导览机器人 R1 | `/robot_0/cmd_vel` | `/robot_0/odom` | `/robot_0/base_scan` | `/robot_0/ground_truth` |
| 配送机器人 R2 | `/robot_1/cmd_vel` | `/robot_1/odom` | `/robot_1/base_scan` | `/robot_1/ground_truth` |

公共接口包括 `/clock`、`/tf`、`/tf_static` 和 `/reset_positions`。

业务接口采用 JSON 字符串，方便后续 LLM 节点输出结构化意图：

| 话题 | 方向 | 用途 |
|---|---|---|
| `/showroom/command` | LLM/终端 → 任务管理器 | 访客意图和操作命令 |
| `/showroom/route_commands` | 任务管理器 → 路线执行器 | 启动、暂停、恢复或取消路线 |
| `/showroom/robot_events` | 路线执行器 → 任务管理器 | 到点、阻塞、清障和完成事件 |
| `/showroom/navigation_status` | 路线执行器 → 监控节点 | 10 Hz 导航状态、阻挡次数与持续时间快照 |
| `/showroom/status` | 任务管理器 → 外部系统 | 双机器人业务状态快照 |
| `/showroom/monitor` | 监控节点 → RQt/终端 | 双机器人运行、障碍与恢复状态快照 |
| `/showroom/response` | 任务管理器 → LLM/界面 | 命令接受或拒绝结果 |
| `/showroom/user_text` | 终端/语音识别 → LLM 桥接器 | 游客自然语言输入 |
| `/showroom/assistant_text` | LLM 桥接器 → 终端/语音合成 | 回复、识别意图和派发结果 |
| `/showroom/llm_status` | LLM 桥接器 → 监控 | 模型连接状态、队列和错误信息 |
| `/showroom/voice/transcript` | ASR → 界面/LLM | 麦克风识别出的游客文字 |
| `/showroom/voice/say` | 终端 → TTS | 直接测试中文语音播报 |
| `/showroom/voice/speaking` | TTS → ASR | 播报期间暂停识别，避免自激回声 |

自动演示会自行发送 `start_tour`。需要手动测试命令时，启动基础 launch：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py -- \
  auto_drive:=true business_mode:=true business_auto_start:=false
```

进入当前会话后发送结构化命令：

```bash
eval "$(ros2 run demo_stage showroom_session env)"

ros2 topic pub --once /showroom/command std_msgs/msg/String \
  "{data: '{\"intent\":\"start_tour\",\"coffee\":true}'}"
```

支持的第一版意图为 `start_tour`、`request_coffee`、`pause_tour`、
`resume_tour`、`cancel_all` 和 `reset`。读取一次当前业务状态：

```bash
ros2 run demo_stage showroom_session business-status
```

## 接入 Windows 上的 Qwen3.5 4B

LLM 桥接器把自然语言转换成经过白名单校验的高层业务命令。模型不能直接发布
`/cmd_vel`，也不能自行生成坐标；运动控制仍由任务管理器和导航节点负责。详细配置与
排错步骤见 [docs/LLM_INTEGRATION.md](docs/LLM_INTEGRATION.md)。

第一次先用不需要网络和模型的 `mock` 后端验证 ROS 2 链路：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py --monitor-windows -- \
  auto_drive:=true business_mode:=true business_auto_start:=false \
  enable_llm:=true llm_backend:=mock
```

在另一个终端发送游客原话，并观察回复：

```bash
ros2 run demo_stage showroom_session exec -- \
  ros2 topic pub --once /showroom/user_text std_msgs/msg/String \
  "{data: '开始导览，不需要咖啡'}"

ros2 run demo_stage showroom_session exec -- \
  ros2 topic echo /showroom/assistant_text --field data --full-length \
  --qos-durability transient_local
```

当前 launch 默认使用已经验证的 Windows Ollama 配置：

- 地址：`http://192.168.23.1:11434`
- 模型：`qwen3.5:4b`
- 后端：`ollama`

因此真实模型模式只需启用 LLM：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py --monitor-windows -- \
  auto_drive:=true business_mode:=true business_auto_start:=false \
  enable_llm:=true
```

需要临时覆盖服务地址时仍可显式传参：

```bash
enable_llm:=true llm_backend:=ollama \
llm_endpoint:=http://192.168.23.1:11434 \
llm_model:=qwen3.5:4b
```

## 真实语音输入输出

语音层使用 PipeWire、faster-whisper 和 Piper，并复用现有的 `/showroom/user_text` 与
`/showroom/assistant_text`，不会改变 LLM 和机器人业务接口。完整说明见
[docs/VOICE_INTEGRATION.md](docs/VOICE_INTEGRATION.md)。

指定场馆配送、导览筛选和 Stage 局部绕障见
[docs/SEMANTIC_ROUTING_AND_AVOIDANCE.md](docs/SEMANTIC_ROUTING_AND_AVOIDANCE.md)。

启用真实语音：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py --monitor-windows -- \
  auto_drive:=true business_mode:=true business_auto_start:=false \
  enable_llm:=true enable_voice:=true
```

持续查看原始状态消息时使用下面的命令。`--full-length` 很重要，否则 `ros2 topic
echo` 默认会把超过 128 个字符的 JSON 截断为 `...`：

```bash
ros2 run demo_stage showroom_session exec -- \
  ros2 topic echo /showroom/status --field data --full-length
```

查看包含仿真时间、航点进度、位姿、速度、雷达前方净空、阻塞时长以及恢复结果的聚合
监控 Topic：

```bash
ros2 run demo_stage showroom_session exec -- \
  ros2 topic echo /showroom/monitor --field data --full-length
```

推荐使用三个终端分层观察：

```bash
# 终端 1：Stage 与全部 ROS 节点
ros2 run demo_stage showroom_session start

# 终端 2：中文简洁看板，按 Ctrl+C 只退出看板
ros2 run demo_stage showroom_session monitor

# 终端 3：开发调试用的完整 JSON
ros2 run demo_stage showroom_session detail-monitor
```

三个终端都要先 source ROS 2 和工作区。只想打印一屏中文状态时，可以执行
`ros2 run demo_stage showroom_session monitor --once`；详细数据同样支持
`detail-monitor --once`，刷新间隔可通过 `detail-monitor --interval 0.1` 调整。

也可以运行 `ros2 run rqt_topic rqt_topic`，在窗口中展开 `/showroom/monitor`。遇到障碍
时对应机器人的 `navigation_state` 变为 `BLOCKED`，`recovery_state` 变为
`WAITING_FOR_CLEARANCE`；移开障碍后分别恢复为 `NAVIGATING` 和
`RESUMED_AFTER_CLEARANCE`，同时保留本次阻塞时长和累计阻塞次数。

## 模拟杂物挡路与恢复

场景入口通道旁放置了一个橙色的 `test_obstacle`。它会被激光雷达检测，并可在 Stage
窗口中拖动。为了有时间先摆放障碍物，关闭业务自动启动：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py -- \
  auto_drive:=true business_mode:=true business_auto_start:=false
```

在 Stage 窗口中左键单击橙色方块选中它，再按住左键把它从初始位置
`(-2.0, -12.5)` 拖到蓝色机器人正前方约 `(0.0, -12.5)`。不要把方块直接叠在
机器人身上；应留出一段距离，让激光雷达先看到它。

然后在另一个终端加入当前会话，观察事件：

```bash
eval "$(ros2 run demo_stage showroom_session env)"
ros2 topic echo /showroom/robot_events
```

再开一个已加入相同会话的终端发送启动命令：

```bash
ros2 topic pub --once /showroom/command std_msgs/msg/String \
  "{data: '{\"intent\":\"start_tour\",\"coffee\":true}'}"
```

蓝色机器人在正前方净空小于 `0.60 m` 时停车，并发布 `blocked` 事件。把橙色方块
拖离通道后，它会发布 `obstacle_cleared`，并从当前航点自动继续。障碍物不移开时，
机器人会一直等待；当前参考控制器还不会绕行或执行 Nav2 式恢复行为。重新启动 Stage
后，橙色方块会回到初始位置。

这里有三种容易混淆的“暂停”：

- 雷达挡停：障碍清除后自动继续。
- `pause_tour` 业务命令：必须发送 `resume_tour` 才继续。
- Stage 窗口按 `p`：冻结整个仿真时钟，再按一次 `p` 恢复。

手动控制导览机器人：

```bash
ros2 topic pub --rate 10 /robot_0/cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.3}, angular: {z: 0.0}}"
```

重置机器人：

```bash
ros2 service call /reset_positions std_srvs/srv/Empty "{}"
```

## 修改地图和路线

`tools/generate_showroom_assets.py` 是栅格地图、路线 YAML、Stage 路线标记和预览图的
生成入口。修改其中的几何体或航点后执行：

```bash
cd /home/xxl/ros2_ws/src/sim_stage/demo_stage
python3 tools/generate_showroom_assets.py
python3 tools/validate_project.py
```

校验器会检查 Python、YAML、XML、Stage include、PGM 尺寸以及机器人路线的
0.42 m 最小几何净空。

## 测试

```bash
cd /home/xxl/ros2_ws
colcon test --packages-select demo_stage
colcon test-result --verbose
```

## 当前边界

- 航点跟随器用于验证地图和 ROS 接口，不包含全局规划、恢复行为或机器人互让。
- 激光急停后不会自动重规划；正式导航应由 Nav2 负责。
- 当前任务协议使用 `std_msgs/String` 承载 JSON；稳定后应提取为独立接口包和 ROS Action。
- 当前可自由组合白名单高层 action；任意地点导航要在接入 Nav2 全局规划后开放。
- 语音层已接入本地 Whisper ASR 和 Piper TTS；VMware 必须把真实麦克风输入正确传给 Ubuntu。
- 隐藏通道目前是静态开口，动态门需要单独的门控节点和 Stage 模型支持。
- Stage 不使用 URDF；接入 Nav2 和 RViz 时需要补充机器人描述、footprint 与代价地图参数。

## VMware 显示问题

如果 Stage GUI 短暂卡住后以退出码 `-6` 结束，同时内核日志包含 `vmwgfx` 或
`Command buffer error`，说明 VMware 虚拟显卡的 OpenGL 命令缓冲区崩溃。项目已默认
设置 `LIBGL_ALWAYS_SOFTWARE=1`，并关闭 GUI 内的实时激光射线绘制。激光话题仍会正常
发布；需要临时查看射线时可在 Stage 的 View 菜单中开启数据绘制。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。
