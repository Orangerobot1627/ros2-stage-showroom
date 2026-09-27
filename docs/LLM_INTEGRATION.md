# Windows Qwen 与 ROS 2 接入说明

## 数据如何流动

```text
游客文字 / 后续语音识别
        │ /showroom/user_text
        ▼
showroom_llm_bridge
        │  HTTP：虚拟机 → Windows 模型服务
        │  JSON 输出校验与意图白名单
        ├────────► /showroom/assistant_text
        │
        └────────► /showroom/command
                         │
                         ▼
                 showroom_task_manager
```

桥接节点同时订阅 `/showroom/status` 和 `/showroom/monitor`，把导览状态、当前航点和障碍
状态压缩后放入提示词。压缩很重要：4B 模型的能力和上下文资源有限，没有必要把完整
雷达数组、位姿历史或整份地图发送给模型。

模型只能输出以下意图：

- `start_tour`，可附带布尔字段 `coffee`
- `request_coffee`
- `pause_tour`
- `resume_tour`
- `cancel_all`
- `reset`
- `ask_status` 和 `chat`，这两类只回复，不下发机器人任务

模型只返回 `{"intent":"pause_tour"}` 也是合法结果，面向游客的确认语由本地协议层
补齐。任何其他意图、格式错误、非布尔的 `coffee` 字段都会在 ROS 侧被拒绝。因此提示词
是第一层约束，代码校验才是实际的安全边界。

## 先验证 ROS 侧

每次修改 Python 节点、launch 或 CMake 安装规则后，都要重新构建并 source：

```bash
source /opt/ros/jazzy/setup.bash
cd /home/xxl/ros2_ws
colcon build --symlink-install --packages-select demo_stage
source install/setup.bash
```

使用 `mock` 后端可以把问题分成两部分。若 mock 能运行，说明 Topic、任务管理器和业务
状态机正常；之后的故障范围只剩 Windows 网络、模型服务地址和模型输出。

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py --monitor-windows -- \
  auto_drive:=true business_mode:=true business_auto_start:=false \
  enable_llm:=true llm_backend:=mock
```

另开一个已 source 的终端：

```bash
ros2 run demo_stage showroom_session exec -- \
  ros2 topic pub --once /showroom/user_text std_msgs/msg/String \
  "{data: '开始导览，不需要咖啡'}"

ros2 run demo_stage showroom_session exec -- \
  ros2 topic echo /showroom/assistant_text --field data --full-length \
  --qos-durability transient_local

ros2 run demo_stage showroom_session exec -- \
  ros2 topic echo /showroom/llm_status --field data --full-length \
  --qos-durability transient_local
```

`/showroom/assistant_text` 使用 transient-local QoS，会保留最近的回复，所以通常可以先发
问题再执行一次 `echo`。`/showroom/user_text` 不保留历史，LLM 节点必须已经启动才能接收。

## 当前 Windows Ollama 部署

当前项目已经使用下面的实际部署完成联调：

- Runtime：Ollama
- API：`http://192.168.23.1:11434`
- Chat API：`http://192.168.23.1:11434/api/chat`
- Model：`qwen3.5:4b`，约 4.7B，`Q4_K_M`
- GPU：RTX 4070 Ti，Ollama 显示 `100% GPU`

连通性检查：

```bash
curl http://192.168.23.1:11434/api/tags
```

这里不要使用 `localhost`。对 Ubuntu 虚拟机来说，`localhost` 指 Ubuntu 自己，不是
Windows 宿主机。

`ROS_DOMAIN_ID` 和 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 只约束 ROS 2 的 DDS
发现，不会阻止桥接节点向 Windows 发普通 HTTP 请求。也就是说，ROS 会话仍然保持隔离，
模型请求则通过你明确填写的 Windows IP 和端口发送。

Ollama 请求显式使用 `think:false`。这类任务只是意图分类，关闭思考后实测只需约 8 个
生成 token；开启思考时相同结果曾使用 871 个生成 token。客户端无论如何都只读取
`message.content`，不会读取或执行 `message.thinking`。

## 启动真实模型后端

Ollama 原生接口：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py --monitor-windows -- \
  auto_drive:=true business_mode:=true business_auto_start:=false \
  enable_llm:=true
```

`ollama`、`http://192.168.23.1:11434`、`qwen3.5:4b` 和 30 秒超时已经是 launch
默认值。需要覆盖时仍可显式指定：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py --monitor-windows -- \
  auto_drive:=true business_mode:=true business_auto_start:=false \
  enable_llm:=true llm_backend:=ollama \
  llm_endpoint:=http://192.168.23.1:11434 \
  llm_model:=qwen3.5:4b
```

`llm_model` 必须使用服务 API 识别的模型 ID，不一定等于模型文件名。4B 模型在 CPU 或
内存紧张的机器上首次推理可能较慢，可以把超时增至 60 秒；桥接器在独立工作线程中等待
HTTP 响应，不会阻塞 ROS 状态订阅和 Stage 仿真。

## 常见故障定位

| 现象 | 检查重点 |
|---|---|
| `Connection refused` | Windows 服务未启动、端口错误或只监听 `127.0.0.1` |
| 请求超时 | Windows 防火墙、VMware 网络模式、首次加载模型过慢 |
| HTTP 404 | endpoint 路径错误；Ollama 是 `/api/chat`，兼容接口通常是 `/v1/chat/completions` |
| 模型未找到 | `llm_model` 与 `/api/tags` 或 `/v1/models` 返回的 ID 不一致 |
| 回复存在但机器人不动 | 查看 `/showroom/assistant_text` 的 `command_dispatched`，再看 `/showroom/response` |
| `intent: error` | 查看 `/showroom/llm_status` 的 `last_error`，通常是输出 JSON 不合规 |

## 代码位置

- `scripts/showroom_ollama_client.py`：Ollama HTTP 通信，只返回 `message.content`。
- `scripts/showroom_llm_prompt.py`：意图 Prompt 和业务状态裁剪。
- `scripts/showroom_llm_contract.py`：JSON 解析、意图白名单、确认语和命令转换。
- `scripts/showroom_llm_core.py`：后端工厂与兼容入口。
- `scripts/showroom_llm_bridge.py`：ROS Topic、后台推理队列和命令发布。
- `tools/test_llm_bridge_logic.py`：解析、白名单、上下文裁剪和 mock 后端测试。
- `launch/showroom.launch.py`：LLM 节点及其 launch 参数。
