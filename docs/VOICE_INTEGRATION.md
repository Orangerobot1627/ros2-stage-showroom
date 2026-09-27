# 真实语音输入输出

## 数据链路

```text
麦克风
  │ PipeWire 16 kHz PCM
  ▼
showroom_asr
  │ 能量 VAD + faster-whisper small/int8
  ├──► /showroom/voice/transcript
  └──► /showroom/user_text
              │
              ▼
      showroom_llm_bridge
              │
              ├──► /showroom/command ──► 机器人行动
              │
              └──► /showroom/assistant_text
                            │
                            ▼
                      showroom_tts
                            │ Piper 中文语音
                            ▼
                       PipeWire 扬声器
```

语音层只接现有文字 Topic，不直接连接任务管理器或速度 Topic。更换 ASR、TTS、仿真器
或机器人底盘时，其他层不需要一起重写。

## 当前本地运行环境

- ASR：`faster-whisper small`，CPU `int8`，中文固定语言
- TTS：Piper `zh_CN-huayan-medium`
- 音频：PipeWire，16 kHz 单声道输入
- Python 依赖：`/home/xxl/ros2_ws/.voice_python`
- ASR 模型：`/home/xxl/ros2_ws/models/faster-whisper-small`
- TTS 模型：`/home/xxl/ros2_ws/models/piper/zh_CN-huayan-medium.onnx`

实测 Piper 生成 2.32 秒中文语音；Whisper 模型加载约 1.36 秒，识别这段音频约 1.10 秒。
模型只在节点启动时加载一次，之后每句话不再重复加载。

## 启动

先构建并 source：

```bash
source /opt/ros/jazzy/setup.bash
cd /home/xxl/ros2_ws
colcon build --symlink-install --packages-select demo_stage
source install/setup.bash
```

启动完整的文字、LLM、语音和机器人链路：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py --monitor-windows -- \
  auto_drive:=true business_mode:=true business_auto_start:=false \
  enable_llm:=true enable_voice:=true
```

默认使用 PipeWire 的默认麦克风和扬声器。查看设备：

```bash
wpctl status
```

指定输入或输出时，可以使用 `wpctl status` 中的序号，也可以使用稳定的 PipeWire 节点名：

```bash
ros2 run demo_stage showroom_session start \
  --launch-file showroom.launch.py -- \
  auto_drive:=true business_mode:=true business_auto_start:=false \
  enable_llm:=true enable_voice:=true \
  voice_input_target:=58 voice_output_target:=49
```

PipeWire 序号在重启后可能变化，长期配置应使用节点名。

## Topic

| Topic | 方向 | 说明 |
|---|---|---|
| `/showroom/voice/transcript` | ASR → 界面 | 最近一次识别文字 |
| `/showroom/user_text` | ASR → LLM | 与手动文字输入共用的入口 |
| `/showroom/voice/say` | 终端 → TTS | 绕过 LLM，直接测试播报 |
| `/showroom/voice/speaking` | TTS → ASR | 播放期间暂停识别，防止自激回声 |
| `/showroom/voice/asr_status` | ASR → 监控 | 模型加载、监听、识别和错误状态 |
| `/showroom/voice/tts_status` | TTS → 监控 | 模型加载、播放和错误状态 |

直接测试扬声器：

```bash
ros2 run demo_stage showroom_session exec -- \
  ros2 topic pub --once /showroom/voice/say std_msgs/msg/String \
  "{data: '您好，科技展馆导览机器人已经准备就绪。'}"
```

查看识别结果：

```bash
ros2 run demo_stage showroom_session exec -- \
  ros2 topic echo /showroom/voice/transcript --field data \
  --qos-durability transient_local
```

## 语音活动检测

ASR 不是按固定时长切录音，而是读取连续 PCM：

1. 音量连续超过阈值 120 ms 后开始一句话。
2. 保留 300 ms 预录音，避免吃掉开头第一个字。
3. 连续静音 900 ms 后结束一句话。
4. 单句话最长 12 秒。
5. Piper 播放期间清空当前录音，防止机器人识别自己的声音。

默认能量阈值为 `250`。环境噪声大导致误触发时提高它，正常说话不触发时降低它：

```bash
enable_voice:=true voice_rms_threshold:=150.0
```

## 当前麦克风状态

VM 中能看到以下输入设备：

- VMware `Ensoniq AudioPCI` 输入
- `UGREEN CM564 USB Audio` 输入

两者目前都能建立 PipeWire 录音流，但采样全部为零。需要在 VMware 的虚拟机设置中确认：

1. 声卡已连接，并勾选启动时连接。
2. Windows 隐私设置允许 VMware 使用麦克风。
3. 如果使用 USB 麦克风，设备已连接到虚拟机而不是仍由 Windows 占用。
4. Ubuntu 设置中的输入电平条会随说话变化。

输入电平恢复后不需要改 ROS 代码，重新启动带 `enable_voice:=true` 的会话即可。

## 已完成的整链验证

使用真实 Windows Ollama 服务和本地语音节点进行了集成测试。输入“请开始带我参观，
不需要咖啡”后得到以下结果：

- Qwen 返回 `start_tour`，并设置 `coffee: false`。
- 任务管理器进入 `TOURING`，蓝色机器人导航节点保持活动。
- Stage 中的蓝色机器人从初始位姿实际移动了 27.96 m。
- Piper 播放回复“已提交导览任务请求。”，`speaking` 状态按 `true → false` 切换。

这说明从识别文字边界开始的 LLM、业务、运动和语音输出链路已经连通。剩余的现场检查是
让 Ubuntu 输入电平条随真实说话变化，以验证 VMware 的物理麦克风通道。
