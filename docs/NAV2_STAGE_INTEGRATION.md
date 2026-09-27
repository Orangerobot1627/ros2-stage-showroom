# Stage 中的轻量 Nav2 配送栈

## 当前范围

`showroom_nav2.launch.py` 把绿色服务机器人 `robot_1` 切换到 Nav2。蓝色导览机器人目前
继续使用已经稳定的语义任务单元和 Stage 航点控制器。这样可以单独验证导航栈，不会同时
改变双机器人业务逻辑和两套底盘控制。

```text
自然语言 / 结构化命令
  -> task manager
  -> semantic navigation request
  -> graph gateway（校验任务地点和业务顺序）
  -> pickup / delivery / standby
  -> Nav2 NavigateToPose
  -> map + costmaps + planner + controller + collision monitor
  -> /robot_1/cmd_vel
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
- 只先迁移服务机器人，避免两套完整 Nav2 栈同时占用 VM CPU。

Stage 已知 `robot_1` 的出生位姿 `(2.3, -14.5, 90°)`，因此这个仿真配置发布固定的
`map -> robot_1/odom` 初始变换，再使用 Stage 的 `odom -> base_link`。实测 3 倍仿真
速度下，AMCL 的雷达消息会因 TF 缓存落后被丢弃并造成定位跳变；固定初始变换既稳定，
也省去粒子滤波开销。`config/nav2_stage_params.yaml` 保留了 AMCL 参数，迁移到 Gazebo 或
实机时应恢复 AMCL/SLAM，并删除这个静态变换。

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

观察 Nav2 生命周期与 Action：

```bash
ros2 run demo_stage showroom_session exec -- \
  ros2 lifecycle get /robot_1/controller_server

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

下一阶段需要为 Nav2 适配器补齐 `pause/resume/cancel` Action 控制，再把蓝色机器人的
动态导览任务单元迁移到第二个命名空间 Nav2 栈。Gazebo/实机阶段再接 AMCL 或 SLAM，
不要保留 Stage 专用的固定 `map -> odom` 变换。
