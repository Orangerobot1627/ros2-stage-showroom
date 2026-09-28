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

两台机器人都支持 `pause/resume/cancel`：暂停会取消当前 Action，但保留计划与当前业务
目标；恢复会从实时位置重新提交目标。蓝色机器人收到 `skip_current`、`next_task`、
`repeat_current`、`skip_task` 或 `visit_only` 后，会在旧 goal 完成取消时原子替换计划，
不会短暂出现两个控制目标。绿色机器人的新配送计划仍会在忙碌时拒绝，防止覆盖载货任务。

下一阶段应补充 Nav2 专用阻挡/恢复遥测，并在两台机器人共享狭窄通道前增加交通预约。
Gazebo/实机阶段再接 AMCL、SLAM 或传感器融合定位。
