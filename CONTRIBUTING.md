# Contributing

## 修改流程

1. 从独立分支开始修改。
2. 地图和路线应通过 `tools/generate_showroom_assets.py` 统一生成。
3. 不要手工修改 `config/routes.yaml`、`world/include/showroom_routes.inc` 或地图文件后跳过生成器。
4. 提交前运行静态校验和 ROS 2 包测试。
5. 交互式仿真使用 `ros2 run demo_stage showroom_session start`，避免复用其他调试会话的 Domain。

```bash
python3 tools/validate_project.py
cd /home/xxl/ros2_ws
colcon test --packages-select demo_stage
colcon test-result --verbose
```

提交应只包含一个明确目的。涉及 ROS 接口变更时，请同步更新 README 和
`docs/ARCHITECTURE.md`。
