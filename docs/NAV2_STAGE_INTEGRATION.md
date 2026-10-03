# Stage 中的双机器人 Nav2 栈

## 当前范围

`showroom_nav2.launch.py` 为蓝色导览机器人 `robot_0` 和绿色服务机器人 `robot_1`
分别启动一套命名空间隔离的 Nav2。基础 `showroom.launch.py` 仍保留轻量 Stage 航点
后端；选择 Nav2 时两个参考航点控制器都会关闭，因此每个 `/cmd_vel` 只有一个所有者。

```text
自然语言 / 结构化命令
  -> task manager
  -> semantic navigation request
  -> graph gateway（校验任务地点和业务顺序）
  -> guide corridor 或 pickup / delivery / standby
  -> /robot_0/navigate_to_pose 或 /robot_1/navigate_to_pose
  -> map + costmaps + planner + controller + collision monitor
  -> /robot_N/cmd_vel
```

旧适配器曾把整条首尾相同的配送环线作为一个 `NavigateThroughPoses` 目标。重规划期间，
Nav2 会逐步删除已经通过的航点，闭环末端可能变成空路径。当前适配器只保留三个业务
目标，每一段完成后等待 Action Server 收尾，再提交下一段。业务层仍会收到 `pickup`、
`delivery`、`returning` 和 `standby` 事件。

## 计算量取舍

当前配置有意选择轻量组件：

- 进程内组合（composition），减少多个 Nav2 进程之间的序列化开销。
- NavFn A* 全局规划器，适合当前单层二维栅格地图。
- Regulated Pure Pursuit 局部控制器，带前向碰撞检查，计算量低于采样型复杂控制器。
- 二维 `ObstacleLayer + InflationLayer`，没有使用 3D voxel layer。
- Velocity Smoother 和 Collision Monitor 串在最终速度通道上。
- 两套 Nav2 使用相同参数模板，在 launch 时重写各自的 base/odom frame。
- Nav2 专用 `showroom_nav2.world` 使用 1 倍实时速率，并把 Stage 速度看门狗放宽为
  3 个仿真秒；基础航点演示继续使用 3 倍速。

Stage 已知两个出生位姿 `(0.0, -14.5, 90°)` 与 `(2.3, -14.5, 90°)`，因此仿真配置分别
发布固定 `map -> robot_N/odom` 初始变换，再使用 Stage 的 `odom -> base_link`。Stage
的 odom 从出生位置的零位姿开始，所以 90°旋转不能省略。固定初始变换省去双 AMCL 的
CPU 开销；迁移到 Gazebo 或实机时应恢复 AMCL/SLAM，并删除这些 Stage 专用变换。

## 启动

```bash
source /opt/ros/jazzy/setup.bash
cd /home/xxl/ros2_ws
colcon build --symlink-install --packages-select demo_stage
source install/setup.bash

ros2 run demo_stage showroom_session start \
  --launch-file showroom_nav2.launch.py --monitor-windows
```

先用确定性的结构化命令测试入口配送：

```bash
ros2 run demo_stage showroom_session exec -- \
  ros2 topic pub --once /showroom/command std_msgs/msg/String \
  "{data: '{\"intent\":\"deliver_drink\",\"drink\":\"coffee\",\"target\":\"reception\"}'}"
```

观察两套 Nav2 生命周期与 Action：

```bash
ros2 run demo_stage showroom_session exec -- \
  ros2 lifecycle get /robot_1/controller_server

ros2 run demo_stage showroom_session exec -- \
  ros2 lifecycle get /robot_0/controller_server

ros2 run demo_stage showroom_session exec -- \
  ros2 action list

ros2 run demo_stage showroom_session exec -- \
  ros2 topic echo /showroom/robot_events --field data --full-length
```

完整实测事件顺序为：

```text
route_started
  -> pickup
  -> depart_pickup
  -> delivery
  -> returning
  -> standby
  -> route_completed
```

## 参考实现

- [Nav2 bringup](https://github.com/ros-navigation/navigation2/tree/jazzy/nav2_bringup)：生命周期、组合节点和多机器人命名空间的官方基线。
- [Nav2 Jazzy parameters](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_bringup/params/nav2_params.yaml)：参数结构的官方参考。
- [Regulated Pure Pursuit](https://github.com/ros-navigation/navigation2/blob/main/nav2_regulated_pure_pursuit_controller/README.md)：低计算量路径跟踪和碰撞时间约束。
- [Collision Monitor](https://github.com/ros-navigation/navigation2/blob/main/nav2_collision_monitor/params/collision_monitor_params.yaml)：独立速度安全层示例。
- [stage_ros2](https://github.com/tuw-robotics/stage_ros2)：Stage 的 ROS 2 话题、TF 和多机器人前缀实现。
- [Nav2 Simple Commander](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_simple_commander/nav2_simple_commander/robot_navigator.py)：Jazzy 中通过 Action goal handle 取消当前任务的官方参考。

## 阻挡、恢复与双机器人相遇

两台机器人都由 Stage 激光雷达观测环境。另一台机器人的实体会进入激光数据，
随后进入各自 Nav2 的障碍层和 Collision Monitor，因此现阶段不需要额外的交通
预约服务器。

`showroom_nav2_adapter.py` 同时订阅本机器人命名空间中的：

- `collision_monitor_state`：Nav2 安全层当前选择的动作；
- `cmd_vel`：经过 Collision Monitor 后最终发给 Stage 的速度。

仅当安全层持续介入、最终线速度和角速度都接近零，并保持超过 1 秒，适配器才
发布一次 `blocked`。正常绕障中的短暂 `APPROACH` 或减速不会累计成阻挡。机器人
重新运动或安全层解除后，经过 0.35 秒去抖会发布 `obstacle_cleared`，Nav2 保留的
目标会继续执行。两台适配器还以 10 Hz 向 `/showroom/navigation_status` 发布持久化
心跳，因此中文监控可以显示当前阻挡时长、上次阻挡时长、累计次数和恢复状态。

当前相遇策略是让 Nav2 把对方当作动态障碍物并自动避让或等待。固定业务优先级
适合作为下一层仲裁规则：导览机器人优先，服务机器人在狭窄位置主动等待；它不
改变 Nav2 的安全停车和自动恢复闭环。

## 航点约束与自由寻路的边界

任务管理器和语义图输出完整的有序航点。Nav2 必须逐个访问这些航点，只在两个相邻
航点之间自由规划、动态绕障。这与官方 `nav2_waypoint_follower` 的工作方式一致：
`FollowWaypoints` 保证访问顺序，内部导航动作负责每一段的实际路径。

配送计划中的 `pickup`、`delivery`、`standby` 是业务阶段标记，不能被当成仅有的运动
目标。中间的走廊航点同样会传入 Nav2。这样绿色机器人可以复用蓝色导览路线到达任意
展厅，同时不会从取货点直接跨区域寻找最短路。当前项目保留自定义适配器，是因为它
还负责暂停、恢复、任务替换以及业务事件；其逐航点执行模型与官方 Waypoint Follower
一致。

## Stage 里程计时间基准

`showroom_final.world` 和 `showroom_nav2.world` 的 `interval_sim` 必须与
`showroom_diff_base` 的 `update_interval` 相同。Stage 的 odom 定位模型每次更新时使用
世界仿真步长积分；如果世界以 50 ms 更新，而 position 模型仍使用默认的 100 ms 更新，
`/robot_N/odom` 只会累计真实位移的一半。Nav2 会在错误的 TF 位姿上判断目标已经到达，
而 Stage 中的机器人已经越过航点数米。

本项目将两者统一为 50 ms，`tools/validate_project.py` 也会在构建和 GitHub Actions 中
拒绝任何不一致的配置。当前 Stage Nav2 配置使用固定 `map -> odom`，所以里程计噪声设为
零；以后接入 AMCL 或其他能够持续修正 `map -> odom` 的定位节点后，才应重新加入噪声。

两台机器人都支持 `pause/resume/cancel`：暂停会取消当前 Action，但保留计划与当前业务
目标；恢复会从实时位置重新提交目标。蓝色机器人收到 `skip_current`、`next_task`、
`repeat_current`、`skip_task` 或 `visit_only` 后，会在旧 goal 完成取消时原子替换计划，
不会短暂出现两个控制目标。绿色机器人的新配送计划仍会在忙碌时拒绝，防止覆盖载货任务。

下一阶段应补充 Nav2 专用阻挡/恢复遥测，并在两台机器人共享狭窄通道前增加交通预约。
Gazebo/实机阶段再接 AMCL、SLAM 或传感器融合定位。
