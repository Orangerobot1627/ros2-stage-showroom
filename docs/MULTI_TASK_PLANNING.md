# Multi-task Planning and Semantic Navigation

This milestone adds a bounded plan format instead of introducing a general
agent framework. A visitor request can contain several goals while every
executable action remains explicit and validated.

Example input:

```text
我想在这个展馆多呆20秒，再送杯饮料来。
```

Normalized model result:

```json
{
  "intent": "execute_plan",
  "plan": [
    {"action": "pause", "robot": "guide", "duration_sec": 20},
    {"action": "deliver_drink", "drink": "coffee", "target": "current_task"}
  ]
}
```

## Execution pipeline

```text
visitor text
  -> Qwen plan JSON
  -> multi-intent normalizer
  -> plan validator
  -> sequential plan executor
  -> task arbitration
  -> semantic navigation request
  -> navigation gateway
       -> Stage graph backend (default)
       -> Nav2 semantic NavigateToPose adapter (optional)
```

The executor advances immediate actions until it reaches an asynchronous step.
`pause` creates the existing renewable human-override lease and completes
immediately. `deliver_drink` waits for the service robot's matching
`route_completed` event. Later actions, such as `announce`, run only after that
event.

The status topic exposes the entire bounded plan under `active_plan`, including
the current step, completed steps, wait condition and failure detail.

## Safe action vocabulary

The first version accepts up to eight actions:

- `pause` and `resume`
- `deliver_drink`
- `skip_current`, `repeat_current`, `next_task`
- `skip_task`, `visit_only`, `temporary_visit`
- `announce`

The model cannot add arbitrary ROS topics, shell commands, coordinates or
velocities. A deterministic normalizer repairs a common Qwen 4B failure mode:
when one sentence contains both a stay request and a drink request, both goals
are preserved even if the model emits only one action.

## Route optimization

`config/navigation_graph.yaml` builds a bidirectional semantic graph from the
already validated guide and delivery routes. A few explicitly checked
connectors join both route networks at open areas. `GraphRoutePlanner` uses
Dijkstra search and an injectable edge-cost interface.

The default cost is geometric distance. Runtime context can add edge penalties,
which is the extension point for congestion, temporary closures, battery cost
or robot-priority rules. Every connector is checked against the generated map
with 0.44 m clearance during project validation.

For a delivery, the gateway optimizes these ordered legs:

```text
service robot position
  -> coffee pickup
  -> accessible point for the requested guide task
  -> service robot standby
```

The Stage backend converts the result into an internal `follow_path` command.
The waypoint follower validates path size, numeric coordinates and segment
length again before motion begins. Mission phases (`pickup`, `delivery`,
`returning`, `standby`) update the business state machine.

## Nav2 boundary

Launch argument `navigation_backend:=stage_graph` is the tested default.
`showroom_nav2.launch.py` starts the tested `navigation_backend:=nav2` profile.
The gateway still validates guide itineraries and delivery destinations.
`showroom_nav2_adapter.py` keeps the three service stops (`pickup`, `delivery`,
`standby`) for `robot_1`, while `robot_0` receives the validated guide corridor
points with semantic task metadata. Each target is submitted as a namespaced
`NavigateToPose` goal so it can be paused, replaced, and replanned independently.

The current launch supplies an isolated TF selection, 2D costmaps, NavFn
planner, Regulated Pure Pursuit controller, velocity smoother and collision
monitor for both robots. It disables both reference waypoint controllers so
each namespaced Nav2 stack is the sole owner of its robot's `/cmd_vel`. See
`NAV2_STAGE_INTEGRATION.md` for the Stage localization and timing choices.

## Referenced upstream designs

- [Nav2 Simple Commander](https://github.com/ros-navigation/navigation2/blob/main/nav2_simple_commander/nav2_simple_commander/robot_navigator.py): non-blocking navigation APIs and namespaced multi-robot clients.
- [Nav2 Waypoint Follower](https://github.com/ros-navigation/navigation2/tree/main/nav2_waypoint_follower): waypoint progress plus task execution at arrival.
- [Open-RMF task sequence](https://github.com/open-rmf/rmf_task): tasks composed from ordered phases with explicit interruption behavior.
- [Open-RMF delivery example](https://github.com/open-rmf/rmf_demos/blob/main/rmf_demos_tasks/rmf_demos_tasks/dispatch_delivery.py): pickup/dropoff descriptions wrapped in a sequence.

Open-RMF is not a dependency of this package. Its full dispatcher, traffic
schedule and fleet adapters are useful later when the project needs shared-space
conflict resolution or larger fleets.

## Try it

Start the normal business simulation with the LLM enabled, then publish:

```bash
ros2 topic pub --once /showroom/user_text std_msgs/msg/String \
  "{data: '我想在这个展馆多呆20秒，再送杯饮料来。'}"
```

Inspect the plan and optimized route:

```bash
ros2 topic echo /showroom/status --field data --full-length
ros2 topic echo /showroom/navigation_events --field data --full-length
```
