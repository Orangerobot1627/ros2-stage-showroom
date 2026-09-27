# 语义路线筛选与 Stage 局部绕障

## 本阶段解决的问题

系统现在把两类导航分开处理：

```text
游客语言
  -> 受控语义命令
  -> 任务管理器
  -> 全馆共享图（决定去哪里）
  -> Stage 局部规划器（决定眼前怎么走）
  -> cmd_vel
```

全馆图同时包含 `guide_full_route` 和 `coffee_delivery_route`。绿色机器人先到
`coffee_pickup`，随后可以使用导览走廊到达七个命名区域中的任意一个配送点，最后返回
待机点。服务专用捷径都经过占用地图 0.42 m 净空检查；导览机器人仍保留完整展厅环线。

支持的场馆 ID：

| ID | 中文区域 |
|---|---|
| `reception` | 入馆接待 |
| `technology_history` | 科技发展历史展区 |
| `vision_hall` | 计算机视觉展厅 |
| `robotics_hall` | 智能机器人展厅 |
| `time_tunnel` | 时空科技隧道 |
| `dance_hall` | 科技舞蹈展厅 |
| `lounge` | 智能休息服务区 |

自然语言示例：

```text
送一杯咖啡到机器人馆
机器人馆我不看了
我只看视觉馆和舞蹈馆
蓝色机器人绕过前面的障碍
```

对应的受控命令分别为 `deliver_drink`、`skip_task`、`visit_only` 和
`robot_action/bypass_obstacle`。中文别名写在 `config/task_units.yaml`，LLM 不接触坐标。

## 局部绕障状态机

`showroom_local_planner.py` 使用雷达的前方、左右前方和左右侧方扇区：

```text
TRACKING
  -> TURNING       选择净空更大的一侧并原地转向
  -> PASSING       低速通过并保持侧向安全距离
  -> REJOINING     重新对准全局航点
  -> TRACKING
```

如果两侧都没有安全空间，机器人进入原有的停车等待流程。监控中的
`local_planner.state`、`avoidance_count` 和 `recovery_state` 可以区分“正在绕行”和
“无路可走而停车”。语音命令可以主动触发一次绕行，正常导航也会在临时障碍进入触发距离
时自动执行。

该模块借鉴 Nav2 的职责划分和局部控制思想，但不是完整 Nav2。完整 Nav2 后端仍负责
AMCL、动态 costmap、全局重规划、DWB/RPP Controller 和标准恢复行为。本阶段的价值是让
Stage 后端具备可观察、可测试的短距离绕障，同时保持以后替换控制器时业务接口不变。

## 参考实现

- [Navigation2](https://github.com/ros-navigation/navigation2)：全局规划、局部控制、行为树和恢复框架。
- [Nav2 DWB Controller](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/dwb_controller/)：候选速度轨迹与障碍评分。
- [Nav2 Regulated Pure Pursuit](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/configuring_regulated_pp/)：前向碰撞检测和曲率限速。
- [Nav2 Collision Monitor](https://github.com/ros-navigation/navigation2/tree/main/nav2_collision_monitor)：独立于规划器的停车/减速安全层。
- [Open-RMF task sequence](https://github.com/open-rmf/rmf_task)：命名地点、GoToPlace、PickUp 和 DropOff 的任务建模。

## 测试

```bash
cd /home/xxl/ros2_ws
colcon test --packages-select demo_stage
colcon test-result --verbose
```

纯算法测试：

```bash
python3 src/sim_stage/demo_stage/tools/test_navigation.py
python3 src/sim_stage/demo_stage/tools/test_local_planner.py
python3 src/sim_stage/demo_stage/tools/test_llm_bridge_logic.py
```
