#!/usr/bin/env python3
"""ROS 2 task manager for the showroom guide and coffee service."""

import json
from pathlib import Path
import time

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from showroom_action_policy import (
    ActionPolicy,
    ActionPolicyError,
    OverrideLeaseBook,
)
from showroom_business_logic import BusinessLogic
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
        elif intent in ('explain_current', 'explain_more'):
            effects = []
            detail = self.task_units.explanation(
                detailed=intent == 'explain_more')
        else:
            if intent in ('cancel_all', 'reset'):
                self.override_leases.clear()
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
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
