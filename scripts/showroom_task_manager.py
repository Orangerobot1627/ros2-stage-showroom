#!/usr/bin/env python3
"""ROS 2 task manager for the showroom guide and coffee service."""

import json
from pathlib import Path
import time

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from showroom_action_policy import (
    ActionPolicy,
    ActionPolicyError,
    OverrideLeaseBook,
)
from showroom_business_logic import BusinessLogic
from showroom_plan import (
    PlanError,
    SequentialPlanExecutor,
    validate_plan,
)
from showroom_task_units import (
    TaskUnitCatalog,
    TaskUnitError,
    TaskUnitTracker,
)
from std_msgs.msg import String


class ShowroomTaskManager(Node):
    """Own the deterministic business state and route dispatch policy."""

    def __init__(self):
        super().__init__('showroom_task_manager')
        self.declare_parameter('command_topic', '/showroom/command')
        self.declare_parameter('event_topic', '/showroom/robot_events')
        self.declare_parameter('route_command_topic', '/showroom/route_commands')
        self.declare_parameter('status_topic', '/showroom/status')
        self.declare_parameter('response_topic', '/showroom/response')
        self.declare_parameter(
            'navigation_request_topic', '/showroom/navigation_requests')
        self.declare_parameter(
            'navigation_event_topic', '/showroom/navigation_events')
        self.declare_parameter(
            'announcement_topic', '/showroom/announcements')
        self.declare_parameter('coffee_trigger', 'tunnel_center_south')
        self.declare_parameter('auto_start', True)
        self.declare_parameter('auto_start_delay_sec', 3.0)
        self.declare_parameter('action_policy_file', '')
        self.declare_parameter('task_units_file', '')
        self.declare_parameter('routes_file', '')
        self.declare_parameter('override_timeout_sec', 0.0)

        policy_file = str(self.get_parameter('action_policy_file').value)
        if policy_file:
            policy_path = Path(policy_file).expanduser()
        else:
            policy_path = Path(get_package_share_directory('demo_stage')) \
                / 'config' / 'action_policy.yaml'
        self.action_policy = ActionPolicy.from_file(policy_path)
        configured_timeout = float(
            self.get_parameter('override_timeout_sec').value)
        if configured_timeout > 0.0:
            self.action_policy.default_duration = self.action_policy.duration(
                configured_timeout)
        self.override_leases = OverrideLeaseBook()
        self.logic = BusinessLogic(
            self.get_parameter('coffee_trigger').value,
            default_routes=self.action_policy.default_routes)
        package_share = Path(get_package_share_directory('demo_stage'))
        configured_tasks = str(self.get_parameter('task_units_file').value)
        configured_routes = str(self.get_parameter('routes_file').value)
        task_path = (
            Path(configured_tasks).expanduser() if configured_tasks
            else package_share / 'config' / 'task_units.yaml')
        route_path = (
            Path(configured_routes).expanduser() if configured_routes
            else package_share / 'config' / 'routes.yaml')
        self.task_units = TaskUnitTracker(
            TaskUnitCatalog.from_files(task_path, route_path))
        self.plan_executor = SequentialPlanExecutor()
        self.plan_sequence = 0
        self.robot_locations = {
            'robot_0': 'entrance',
            'robot_1': 'coffee_robot_standby',
        }
        route_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        status_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.route_publisher = self.create_publisher(
            String,
            self.get_parameter('route_command_topic').value,
            route_qos,
        )
        self.status_publisher = self.create_publisher(
            String,
            self.get_parameter('status_topic').value,
            status_qos,
        )
        self.response_publisher = self.create_publisher(
            String,
            self.get_parameter('response_topic').value,
            10,
        )
        self.navigation_request_publisher = self.create_publisher(
            String,
            self.get_parameter('navigation_request_topic').value,
            route_qos,
        )
        self.announcement_publisher = self.create_publisher(
            String,
            self.get_parameter('announcement_topic').value,
            10,
        )
        self.create_subscription(
            String,
            self.get_parameter('command_topic').value,
            self.command_callback,
            10,
        )
        self.create_subscription(
            String,
            self.get_parameter('event_topic').value,
            self.event_callback,
            50,
        )
        self.create_subscription(
            String,
            self.get_parameter('navigation_event_topic').value,
            self.navigation_event_callback,
            20,
        )
        self.create_timer(1.0, self.publish_periodic_status)
        self.create_timer(0.2, self.expire_overrides)

        self.auto_start_timer = None
        if self.get_parameter('auto_start').value:
            delay = float(
                self.get_parameter('auto_start_delay_sec').value)
            self.auto_start_deadline = self.get_clock().now() + Duration(
                seconds=delay)
            self.auto_start_timer = self.create_timer(
                0.1, self.auto_start_callback)
            self.get_logger().info(
                f'Business demo will start in {delay:.1f} simulation seconds')
        else:
            self.get_logger().info(
                'Waiting for structured commands on /showroom/command')

    def timestamp(self):
        return self.get_clock().now().nanoseconds / 1e9

    def publish_json(self, publisher, document):
        payload = dict(document)
        payload.setdefault('stamp', self.timestamp())
        message = String()
        message.data = json.dumps(
            payload, ensure_ascii=False, separators=(',', ':'))
        publisher.publish(message)

    def apply_effects(self, effects):
        for effect in effects:
            if effect.get('type') == 'route_command':
                self.publish_json(self.route_publisher, effect)
                self.get_logger().info(
                    f'Dispatch {effect["action"]} to '
                    f'{effect["robot_id"]}: {effect["route"]}')
            elif effect.get('type') == 'navigation_request':
                self.publish_json(self.navigation_request_publisher, effect)
                self.get_logger().info(
                    f'Dispatch navigation mission {effect["mission_id"]} '
                    f'type={effect["request_type"]} '
                    f'target={effect.get("service_target") or effect.get("task_ids")}')
            elif effect.get('type') == 'announcement':
                self.publish_json(self.announcement_publisher, effect)

    def publish_status(self, reason):
        status = self.logic.snapshot()
        overrides = self.override_leases.snapshot(time.monotonic())
        status.update({
            'human_override_active': bool(overrides),
            'human_overrides': overrides,
            'override_default_duration_sec': (
                self.action_policy.default_duration),
            'override_time_source': 'steady_wall_clock',
            'current_task': self.task_units.snapshot(),
            'active_plan': self.plan_executor.snapshot(),
        })
        status.update({'type': 'business_status', 'reason': reason})
        self.publish_json(self.status_publisher, status)

    def publish_periodic_status(self):
        self.publish_status('periodic')

    def publish_response(self, accepted, intent, detail):
        self.publish_json(self.response_publisher, {
            'type': 'command_response',
            'accepted': accepted,
            'intent': intent,
            'detail': detail,
        })

    @staticmethod
    def parse_message(message):
        document = json.loads(message.data)
        if not isinstance(document, dict):
            raise ValueError('JSON payload must be an object')
        return document

    def pause_with_lease(self, robot_ids, duration):
        """Pause active missions and remember how to resume each one."""
        now = time.monotonic()
        effects = []
        affected = []
        for robot_id in robot_ids:
            existing = self.override_leases.get(robot_id)
            if existing is not None:
                self.override_leases.begin(
                    robot_id, 'pause', now, duration,
                    existing.base_state, existing.resume_required)
                affected.append(robot_id)
                continue
            base_state = self.logic.state_for(robot_id)
            try:
                pause_effects = self.logic.pause_robot(robot_id)
            except ValueError:
                continue
            effects.extend(pause_effects)
            self.override_leases.begin(
                robot_id, 'pause', now, duration,
                base_state, bool(pause_effects))
            affected.append(robot_id)
        if not affected:
            raise ValueError('No selected robot has an active mission to pause')
        return effects, affected

    def resume_from_override(self, robot_ids):
        """Release human control and continue suspended default missions."""
        effects = []
        affected = []
        for robot_id in robot_ids:
            lease = self.override_leases.release(robot_id)
            if lease is None and self.logic.state_for(robot_id) != 'PAUSED':
                continue
            try:
                effects.extend(self.logic.resume_robot(robot_id))
                affected.append(robot_id)
            except ValueError:
                if lease is not None:
                    affected.append(robot_id)
        if not affected:
            raise ValueError('No selected robot has a suspended mission')
        return effects, affected

    def execute_robot_action(self, document):
        """Execute one validated, policy-controlled high-level action."""
        target = document.get('robot')
        action = self.action_policy.validate_action(
            document.get('action'), target)
        robot_ids = self.action_policy.resolve_robots(target)
        if action == 'bypass_obstacle':
            return [
                {
                    'type': 'route_command',
                    'robot_id': robot_id,
                    'route': self.logic.route_for(robot_id),
                    'action': 'bypass_obstacle',
                }
                for robot_id in robot_ids
            ], f'local obstacle bypass requested for {robot_ids}'
        if action == 'pause':
            duration = self.action_policy.duration(
                document.get('duration_sec'))
            effects, affected = self.pause_with_lease(robot_ids, duration)
            return effects, (
                f'paused {affected} for {duration:.1f}s; '
                'default mission will resume automatically')
        if action == 'resume':
            effects, affected = self.resume_from_override(robot_ids)
            return effects, f'resumed default mission for {affected}'

        effects = []
        for robot_id in robot_ids:
            self.override_leases.release(robot_id)
            if action == 'start_default':
                effects.extend(self.logic.start_default(robot_id))
                if robot_id == 'robot_0':
                    self.task_units.start()
            elif action == 'cancel':
                effects.extend(self.logic.cancel_robot(robot_id))
                if robot_id == 'robot_0':
                    self.task_units.clear()
        return effects, f'{action} accepted for {robot_ids}'

    def execute_task_edit(self, intent):
        """Edit the guide route at semantic task boundaries."""
        guide_state = self.logic.state_for('robot_0')
        if guide_state not in (
                'RECEPTION', 'TOURING', 'GOING_TO_LOUNGE',
                'PAUSED', 'BLOCKED'):
            raise TaskUnitError('蓝色导览机器人当前没有可编辑的导览任务')

        effects = []
        self.override_leases.release('robot_0')
        if guide_state == 'PAUSED':
            effects.extend(self.logic.resume_robot('robot_0'))
        elif guide_state == 'BLOCKED':
            previous = self.logic.blocked_from.pop('robot_0', 'TOURING')
            self.logic.guide_state = previous

        route_effect, previous, target = self.task_units.edit(intent)
        effects.append(route_effect)
        if intent == 'repeat_current':
            detail = f'重新执行当前任务：{target.display_name}'
        elif intent == 'skip_current':
            detail = (
                f'已跳过 {previous.display_name}，下一任务：'
                f'{target.display_name}')
        else:
            detail = f'进入下一任务：{target.display_name}'
        return effects, detail

    def resolve_plan_target(self, target):
        """Resolve current_task or an explicit safe semantic task id."""
        if target == 'current_task':
            unit = self.task_units.current
            if unit is None:
                raise PlanError('当前没有可作为配送目标的导览任务')
            return unit
        return self.task_units.catalog.resolve(target)

    def next_mission_id(self, prefix):
        self.plan_sequence += 1
        return f'{prefix}-{self.plan_sequence:04d}'

    def delivery_effect(self, target, beverage, mission_id=None):
        """Reserve robot_1 and create one semantic pickup/dropoff request."""
        unit = self.resolve_plan_target(target)
        self.logic.begin_delivery(unit.task_id, beverage)
        mission_id = mission_id or self.next_mission_id('delivery')
        return {
            'type': 'navigation_request',
            'request_type': 'delivery',
            'robot_id': 'robot_1',
            'route': self.logic.route_for('robot_1'),
            'mission_id': mission_id,
            'start': self.robot_locations.get(
                'robot_1', 'coffee_robot_standby'),
            'service_target': unit.task_id,
            'beverage': beverage,
        }, unit

    def execute_task_selection(self, intent, requested_tasks):
        """Replan the guide over selected task units on the shared graph."""
        if self.logic.state_for('robot_0') not in (
                'RECEPTION', 'TOURING', 'GOING_TO_LOUNGE',
                'PAUSED', 'BLOCKED'):
            raise TaskUnitError('蓝色导览机器人当前没有可重规划的导览任务')
        catalog = self.task_units.catalog
        previous_current = self.task_units.current
        requested = catalog.ordered(requested_tasks)
        requested_ids = [unit.task_id for unit in requested]
        current_index = self.task_units.current_index or 0
        remaining = catalog.units[current_index:]
        if intent == 'skip_task':
            remaining_ids = {unit.task_id for unit in remaining}
            if not remaining_ids.intersection(requested_ids):
                raise TaskUnitError('指定场馆已经参观完毕，不在后续导览中')
            selected = [
                unit for unit in remaining
                if unit.task_id not in set(requested_ids)]
            skipped = requested_ids
        else:
            selected = requested
            skipped = [
                unit.task_id for unit in remaining
                if unit.task_id not in set(requested_ids)]
            # The lounge is the safe end state, not an extra exhibit.
            lounge = catalog.unit_for_id('lounge')
            if lounge.task_id not in {unit.task_id for unit in selected}:
                selected.append(lounge)
                skipped = [
                    task_id for task_id in skipped
                    if task_id != lounge.task_id]
        if not selected:
            raise TaskUnitError('筛选后没有剩余导览任务')
        selected = catalog.ordered([unit.task_id for unit in selected])
        self.override_leases.release('robot_0')
        if self.logic.guide_state == 'PAUSED':
            self.logic.paused_from.pop('robot_0', None)
        if self.logic.guide_state == 'BLOCKED':
            self.logic.blocked_from.pop('robot_0', None)
        self.logic.guide_state = 'TOURING'
        self.task_units.set_itinerary(
            [unit.task_id for unit in selected], skipped=skipped)
        mission_id = self.next_mission_id('guide')
        effect = {
            'type': 'navigation_request',
            'request_type': 'guide_itinerary',
            'robot_id': 'robot_0',
            'route': self.logic.route_for('robot_0'),
            'mission_id': mission_id,
            'start': self.robot_locations.get('robot_0', 'entrance'),
            'task_ids': [unit.task_id for unit in selected],
            'resume_task_id': (
                previous_current.task_id
                if previous_current is not None
                and previous_current.task_id in {
                    unit.task_id for unit in selected}
                else None),
        }
        names = '、'.join(unit.display_name for unit in selected)
        return [effect], f'guide itinerary {mission_id}: {names}'

    def execute_plan_action(self, action):
        """Execute one normalized action and return effects/detail/wait."""
        action_name = action['action']
        if action_name == 'pause':
            self.action_policy.validate_action('pause', action['robot'])
            robot_ids = self.action_policy.resolve_robots(action['robot'])
            effects, affected = self.pause_with_lease(
                robot_ids, action['duration_sec'])
            return effects, f'paused {affected}', None
        if action_name == 'resume':
            self.action_policy.validate_action('resume', action['robot'])
            robot_ids = self.action_policy.resolve_robots(action['robot'])
            effects, affected = self.resume_from_override(robot_ids)
            return effects, f'resumed {affected}', None
        if action_name in TaskUnitTracker.EDIT_INTENTS:
            effects, detail = self.execute_task_edit(action_name)
            return effects, detail, None
        if action_name in ('skip_task', 'visit_only'):
            effects, detail = self.execute_task_selection(
                action_name, action['tasks'])
            return effects, detail, None
        if action_name == 'bypass_obstacle':
            effects, detail = self.execute_robot_action({
                'robot': action['robot'], 'action': 'bypass_obstacle'})
            return effects, detail, None
        if action_name == 'announce':
            effect = {
                'type': 'announcement',
                'plan_id': self.plan_executor.plan_id,
                'text': action['text'],
            }
            return [effect], action['text'], None
        if action_name == 'deliver_drink':
            beverage = action['drink']
            mission_id = (
                f'{self.plan_executor.plan_id}-step-'
                f'{self.plan_executor.current_index + 1}')
            effect, unit = self.delivery_effect(
                action['target'], beverage, mission_id=mission_id)
            wait_for = {
                'type': 'route_completed',
                'robot_id': 'robot_1',
                'mission_id': mission_id,
            }
            return [effect], (
                f'{beverage} delivery to {unit.display_name}'), wait_for
        raise PlanError(f'未实现 plan action：{action_name!r}')

    def preflight_plan(self, actions):
        """Resolve resources and semantic targets before mutating robot state."""
        for action in actions:
            action_name = action['action']
            if action_name in ('pause', 'resume'):
                self.action_policy.validate_action(
                    action_name, action['robot'])
                self.action_policy.resolve_robots(action['robot'])
            elif action_name in TaskUnitTracker.EDIT_INTENTS:
                if self.logic.state_for('robot_0') not in (
                        'RECEPTION', 'TOURING', 'GOING_TO_LOUNGE',
                        'PAUSED', 'BLOCKED'):
                    raise PlanError('当前没有可编辑的导览任务')
            elif action_name in ('skip_task', 'visit_only'):
                self.task_units.catalog.ordered(action['tasks'])
                if self.logic.state_for('robot_0') not in (
                        'RECEPTION', 'TOURING', 'GOING_TO_LOUNGE',
                        'PAUSED', 'BLOCKED'):
                    raise PlanError('当前没有可重规划的导览任务')
            elif action_name == 'bypass_obstacle':
                self.action_policy.validate_action(
                    'bypass_obstacle', action['robot'])
            elif action_name == 'deliver_drink':
                self.resolve_plan_target(action['target'])
                if self.logic.coffee_state in (
                        'TO_PICKUP', 'PICKUP', 'DELIVERING', 'DELIVERED',
                        'RETURNING', 'PAUSED', 'BLOCKED'):
                    raise PlanError('绿色服务机器人已有配送任务')

    def advance_plan(self):
        """Run immediate steps until an asynchronous step or completion."""
        effects = []
        while self.plan_executor.state == 'RUNNING':
            action = self.plan_executor.begin_current()
            try:
                step_effects, detail, wait_for = self.execute_plan_action(action)
            except (ActionPolicyError, PlanError, TaskUnitError, ValueError) \
                    as exception:
                self.plan_executor.fail(exception)
                raise
            effects.extend(step_effects)
            if wait_for is None:
                self.plan_executor.complete_current(detail)
            else:
                self.plan_executor.wait_current(wait_for, detail)
                break
        return effects

    def execute_plan(self, document, source):
        """Validate and start one bounded multi-step visitor plan."""
        actions = validate_plan(
            document.get('plan'),
            default_pause_sec=self.action_policy.default_duration)
        self.preflight_plan(actions)
        self.plan_sequence += 1
        plan_id = str(document.get('plan_id') or (
            f'plan-{self.plan_sequence:04d}'))
        self.plan_executor.start(plan_id, actions, source=source)
        effects = self.advance_plan()
        detail = (
            f'{plan_id} accepted: {len(actions)} steps, '
            f'state={self.plan_executor.state}')
        return effects, detail

    def execute_command(self, document, source):
        intent = document.get('intent') or document.get('command')
        detail = 'accepted'
        if intent == 'pause_tour':
            duration = self.action_policy.duration(
                document.get('duration_sec'))
            effects, affected = self.pause_with_lease(
                ['robot_0'], duration)
            detail = (
                f'paused {affected} for {duration:.1f}s; '
                'default mission will resume automatically')
        elif intent == 'resume_tour':
            effects, affected = self.resume_from_override(['robot_0'])
            detail = f'resumed default mission for {affected}'
        elif intent == 'robot_action':
            effects, detail = self.execute_robot_action(document)
        elif intent in TaskUnitTracker.EDIT_INTENTS:
            effects, detail = self.execute_task_edit(intent)
        elif intent in ('skip_task', 'visit_only'):
            effects, detail = self.execute_task_selection(
                intent, document.get('tasks') or [])
        elif intent == 'deliver_drink':
            effect, unit = self.delivery_effect(
                document.get('target', 'current_task'),
                document.get('drink', 'coffee'))
            effects = [effect]
            detail = (
                f'{document.get("drink", "coffee")} delivery to '
                f'{unit.display_name}')
        elif intent in ('explain_current', 'explain_more'):
            effects = []
            detail = self.task_units.explanation(
                detailed=intent == 'explain_more')
        elif intent == 'execute_plan':
            effects, detail = self.execute_plan(document, source)
        else:
            if intent in ('cancel_all', 'reset'):
                self.override_leases.clear()
                if self.plan_executor.active:
                    self.plan_executor.cancel(intent)
            effects = self.logic.handle_command(document)
            if intent == 'start_tour':
                self.task_units.start()
            elif intent in ('cancel_all', 'reset'):
                self.task_units.clear()
        self.apply_effects(effects)
        self.publish_status(f'{source}:{intent}')
        self.publish_response(True, intent, detail)

    def expire_overrides(self):
        """Resume defaults after a wall-clock human-control lease expires."""
        if not self.action_policy.auto_resume:
            return
        expired = self.override_leases.expired(time.monotonic())
        if not expired:
            return
        effects = []
        resumed = []
        for lease in expired:
            if not lease.resume_required:
                continue
            try:
                effects.extend(self.logic.resume_robot(lease.robot_id))
                resumed.append(lease.robot_id)
            except ValueError as exception:
                self.get_logger().warning(
                    f'Could not restore {lease.robot_id}: {exception}')
        self.apply_effects(effects)
        self.publish_status('human_override_expired')
        if resumed:
            self.get_logger().info(
                f'Human override expired; resumed defaults for {resumed}')

    def command_callback(self, message):
        intent = None
        try:
            document = self.parse_message(message)
            intent = document.get('intent') or document.get('command')
            self.execute_command(document, 'visitor_command')
        except (ActionPolicyError, json.JSONDecodeError,
                TypeError, ValueError) as exception:
            self.get_logger().warning(f'Rejected command: {exception}')
            self.publish_response(False, intent, str(exception))

    def event_callback(self, message):
        try:
            document = self.parse_message(message)
            event_type = document.get('type')
            robot_id = document.get('robot_id')
            if robot_id in self.robot_locations and document.get('label'):
                self.robot_locations[robot_id] = document['label']
            if event_type in ('route_cancelled', 'route_completed'):
                self.override_leases.release(robot_id)
            if robot_id == 'robot_0':
                if event_type == 'route_started':
                    if self.task_units.current is None:
                        self.task_units.start()
                elif event_type == 'waypoint_reached':
                    self.task_units.observe_waypoint(
                        document.get('label'), document.get('index'))
                elif event_type == 'route_seeked':
                    self.task_units.observe_seek(
                        document.get('label'), document.get('index'),
                        document.get('task_id'))
                elif event_type == 'route_cancelled':
                    self.task_units.clear()
            effects = self.logic.handle_event(document)
            mission_id = document.get('mission_id')
            if (event_type in ('route_failed', 'route_command_rejected')
                    and self.plan_executor.active
                    and mission_id
                    == (self.plan_executor.wait_for or {}).get('mission_id')):
                self.plan_executor.fail(
                    document.get('reason', event_type))
            elif self.plan_executor.observe_event(document):
                self.robot_locations['robot_1'] = 'coffee_robot_standby'
                effects.extend(self.advance_plan())
            for effect in effects:
                if (effect.get('type') == 'route_command'
                        and effect.get('robot_id') == 'robot_1'
                        and effect.get('action') == 'start'):
                    self.get_logger().info(
                        'Coffee route triggered by '
                        f'{document.get("robot_id")} reaching '
                        f'{document.get("label")!r}')
            self.apply_effects(effects)
            event_name = document.get('type', 'unknown')
            event_label = document.get('label', '')
            self.publish_status(f'robot_event:{event_name}:{event_label}')
        except (TaskUnitError, json.JSONDecodeError,
                TypeError, ValueError) as exception:
            self.get_logger().warning(f'Ignored robot event: {exception}')

    def navigation_event_callback(self, message):
        """Observe route planning acceptance or rejection."""
        try:
            document = self.parse_message(message)
            if (document.get('type') == 'navigation_rejected'
                    and self.plan_executor.active
                    and document.get('mission_id')
                    == (self.plan_executor.wait_for or {}).get('mission_id')):
                self.plan_executor.fail(
                    document.get('reason', 'navigation rejected'))
            self.publish_status(
                f'navigation_event:{document.get("type", "unknown")}')
        except (json.JSONDecodeError, TypeError, ValueError) as exception:
            self.get_logger().warning(
                f'Ignored navigation event: {exception}')

    def auto_start_callback(self):
        if self.get_clock().now() < self.auto_start_deadline:
            return
        self.auto_start_timer.cancel()
        try:
            self.execute_command({
                'intent': 'start_tour',
                'coffee': True,
            }, 'auto_start')
        except ValueError as exception:
            self.get_logger().error(f'Auto-start failed: {exception}')


def main(args=None):
    rclpy.init(args=args)
    node = ShowroomTaskManager()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
