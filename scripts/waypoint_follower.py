#!/usr/bin/env python3

import json
import math
from pathlib import Path

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    qos_profile_sensor_data,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
import yaml


def normalize_angle(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class WaypointFollower(Node):
    def __init__(self):
        super().__init__('waypoint_follower')

        self.declare_parameter('route_file', '')
        self.declare_parameter('route_name', 'guide_full_route')
        self.declare_parameter('start_delay_sec', 0.0)
        self.declare_parameter('max_linear_speed', 0.60)
        self.declare_parameter('max_angular_speed', 1.20)
        self.declare_parameter('goal_tolerance', 0.30)
        self.declare_parameter('heading_tolerance', 0.30)
        self.declare_parameter('obstacle_stop_distance', 0.60)
        self.declare_parameter('pose_topic', 'ground_truth')
        self.declare_parameter('scan_topic', 'base_scan')
        self.declare_parameter('loop', False)
        self.declare_parameter('robot_id', '')
        self.declare_parameter('wait_for_start_command', False)
        self.declare_parameter(
            'command_topic', '/showroom/route_commands')
        self.declare_parameter(
            'event_topic', '/showroom/robot_events')
        self.declare_parameter(
            'navigation_status_topic', '/showroom/navigation_status')

        route_file = Path(self.get_parameter('route_file').value)
        route_name = self.get_parameter('route_name').value
        if not route_file.is_file():
            raise FileNotFoundError(f'Route file does not exist: {route_file}')

        with route_file.open('r', encoding='utf-8') as stream:
            document = yaml.safe_load(stream)

        route = document.get('routes', {}).get(route_name)
        if route is None:
            available = ', '.join(sorted(document.get('routes', {}).keys()))
            raise KeyError(f'Unknown route {route_name!r}; available routes: {available}')

        self.default_waypoints = [dict(item) for item in route['waypoints']]
        self.waypoints = [dict(item) for item in self.default_waypoints]
        if not self.default_waypoints:
            raise ValueError(f'Route {route_name!r} contains no waypoints')

        self.route_name = route_name
        self.start_delay = float(self.get_parameter('start_delay_sec').value)
        self.max_linear = float(self.get_parameter('max_linear_speed').value)
        self.max_angular = float(self.get_parameter('max_angular_speed').value)
        self.goal_tolerance = float(self.get_parameter('goal_tolerance').value)
        self.heading_tolerance = float(self.get_parameter('heading_tolerance').value)
        self.stop_distance = float(self.get_parameter('obstacle_stop_distance').value)
        self.pose_topic = self.get_parameter('pose_topic').value
        self.loop = bool(self.get_parameter('loop').value)
        self.robot_id = self.get_parameter('robot_id').value
        if not self.robot_id:
            self.robot_id = self.get_namespace().strip('/')
        self.wait_for_start = bool(
            self.get_parameter('wait_for_start_command').value)

        self.pose = None
        self.front_clearance = math.inf
        self.index = 0
        self.finished = False
        self.active = not self.wait_for_start
        self.blocked = False
        self.blocked_since = None
        self.last_blocked_duration = 0.0
        self.block_count = 0
        self.dynamic_path = False
        self.mission_context = {}
        self.start_time = self.get_clock().now()
        # start_delay_sec is only for autonomous startup. A task-manager start
        # command is itself the scheduling decision and must take effect now.
        self.activation_delay = self.start_delay if self.active else 0.0

        self.cmd_pub = self.create_publisher(Twist, 'cmd_vel', 10)
        state_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.event_pub = self.create_publisher(
            String,
            self.get_parameter('event_topic').value,
            state_qos,
        )
        self.navigation_status_pub = self.create_publisher(
            String,
            self.get_parameter('navigation_status_topic').value,
            state_qos,
        )
        command_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            String,
            self.get_parameter('command_topic').value,
            self.command_callback,
            command_qos,
        )
        self.create_subscription(Odometry, self.pose_topic, self.pose_callback, 10)
        self.create_subscription(
            LaserScan,
            self.get_parameter('scan_topic').value,
            self.scan_callback,
            qos_profile_sensor_data,
        )
        self.create_timer(0.10, self.control_step)

        self.get_logger().info(
            f'Loaded {len(self.waypoints)} waypoints from route {route_name!r}; '
            f'pose topic={self.pose_topic!r}; autonomous start delay='
            f'{self.start_delay:.1f}s; '
            f'active={self.active}')
        if self.active:
            self.publish_event('route_started')

    def publish_event(self, event_type, **fields):
        document = {
            'type': event_type,
            'robot_id': self.robot_id,
            'route': self.route_name,
            'stamp': self.get_clock().now().nanoseconds / 1e9,
        }
        document.update(self.mission_context)
        document.update(fields)
        message = String()
        message.data = json.dumps(
            document, ensure_ascii=False, separators=(',', ':'))
        self.event_pub.publish(message)

    def timestamp(self):
        return self.get_clock().now().nanoseconds / 1e9

    def publish_navigation_status(self, now=None):
        """Publish durable current state; events alone are not state storage."""
        if now is None:
            now = self.timestamp()
        blocked_duration = 0.0
        if self.blocked_since is not None:
            blocked_duration = max(0.0, now - self.blocked_since)
        clearance = None
        if math.isfinite(self.front_clearance):
            clearance = round(self.front_clearance, 3)
        target = None
        if not self.finished and self.index < len(self.waypoints):
            target = self.waypoints[self.index].get(
                'label', f'waypoint_{self.index}')
        document = {
            'type': 'navigation_status',
            'robot_id': self.robot_id,
            'route': self.route_name,
            'stamp': now,
            'active': self.active,
            'finished': self.finished,
            'blocked': self.blocked,
            'blocked_since_sec': self.blocked_since,
            'blocked_duration_sec': round(blocked_duration, 3),
            'last_blocked_duration_sec': round(
                self.last_blocked_duration, 3),
            'block_count': self.block_count,
            'front_clearance_m': clearance,
            'target_waypoint': target,
            'dynamic_path': self.dynamic_path,
            'mission_id': self.mission_context.get('mission_id'),
            'service_target': self.mission_context.get('service_target'),
        }
        message = String()
        message.data = json.dumps(
            document, ensure_ascii=False, separators=(',', ':'))
        self.navigation_status_pub.publish(message)

    def command_callback(self, message):
        try:
            document = json.loads(message.data)
        except (json.JSONDecodeError, TypeError):
            self.get_logger().warning('Ignored malformed route command')
            return
        if document.get('robot_id') != self.robot_id:
            return
        if document.get('route') not in (None, self.route_name):
            return

        action = document.get('action')
        if action == 'start':
            self.waypoints = [dict(item) for item in self.default_waypoints]
            self.dynamic_path = False
            self.mission_context = {}
            self.index = 0
            self.finished = False
            self.active = True
            self.blocked = False
            self.blocked_since = None
            self.start_time = self.get_clock().now()
            self.activation_delay = 0.0
            self.publish_event('route_started')
            self.publish_navigation_status()
            self.get_logger().info(
                f'Started route {self.route_name!r} by task command')
        elif action == 'follow_path':
            try:
                waypoints = self.validate_dynamic_path(
                    document.get('waypoints'))
            except ValueError as exception:
                self.get_logger().warning(
                    f'Rejected dynamic path: {exception}')
                self.publish_event(
                    'route_command_rejected', action='follow_path',
                    reason=str(exception),
                    mission_id=document.get('mission_id'))
                return
            self.waypoints = waypoints
            self.dynamic_path = True
            self.mission_context = {
                key: document.get(key)
                for key in ('mission_id', 'service_target', 'beverage')
                if document.get(key) is not None
            }
            self.index = 0
            self.finished = False
            self.active = True
            self.blocked = False
            self.blocked_since = None
            self.start_time = self.get_clock().now()
            self.activation_delay = 0.0
            self.publish_stop()
            self.publish_event(
                'route_started', dynamic_path=True,
                total=len(self.waypoints),
                distance_m=document.get('distance_m'),
                cost=document.get('cost'),
                cost_profile=document.get('cost_profile'))
            self.publish_navigation_status()
            self.get_logger().info(
                f'Started optimized path {self.mission_context.get("mission_id")!r} '
                f'with {len(self.waypoints)} waypoints')
        elif action == 'pause' and not self.finished:
            self.active = False
            self.publish_stop()
            self.publish_event('route_paused')
            self.publish_navigation_status()
            self.get_logger().info(f'Paused route {self.route_name!r}')
        elif action == 'resume' and not self.finished:
            self.active = True
            self.start_time = self.get_clock().now()
            self.activation_delay = 0.0
            self.publish_event('route_resumed')
            self.publish_navigation_status()
            self.get_logger().info(f'Resumed route {self.route_name!r}')
        elif action == 'seek':
            target_index = document.get('waypoint_index')
            if (isinstance(target_index, bool)
                    or not isinstance(target_index, int)
                    or not 0 <= target_index < len(self.waypoints)):
                self.get_logger().warning(
                    f'Rejected invalid seek index: {target_index!r}')
                self.publish_event(
                    'route_command_rejected', action='seek',
                    reason='invalid_waypoint_index')
                return
            self.index = target_index
            self.finished = False
            self.active = True
            self.blocked = False
            self.blocked_since = None
            self.activation_delay = 0.0
            label = self.waypoints[self.index].get(
                'label', f'waypoint_{self.index}')
            self.publish_stop()
            self.publish_event(
                'route_seeked',
                label=label,
                index=self.index + 1,
                total=len(self.waypoints),
                task_id=document.get('task_id'),
                task_edit=document.get('task_edit'),
            )
            self.publish_navigation_status()
            self.get_logger().info(
                f'Seek route to {self.index + 1}/{len(self.waypoints)}: '
                f'{label}')
        elif action == 'cancel':
            self.active = False
            self.finished = True
            self.publish_stop()
            self.publish_event('route_cancelled')
            self.publish_navigation_status()
            self.get_logger().info(f'Cancelled route {self.route_name!r}')

    @staticmethod
    def validate_dynamic_path(waypoints):
        """Validate an internal planned path before it reaches motion control."""
        if not isinstance(waypoints, list) or not 1 <= len(waypoints) <= 256:
            raise ValueError('waypoints must contain 1..256 items')
        validated = []
        previous = None
        allowed_metadata = {
            'mission_id', 'service_target', 'beverage', 'mission_phase'}
        for index, item in enumerate(waypoints):
            if not isinstance(item, dict):
                raise ValueError(f'waypoint {index} must be an object')
            try:
                x = float(item['x'])
                y = float(item['y'])
            except (KeyError, TypeError, ValueError) as exception:
                raise ValueError(
                    f'waypoint {index} needs numeric x/y') from exception
            label = str(item.get('label', '')).strip()
            if not math.isfinite(x) or not math.isfinite(y) or not label:
                raise ValueError(f'waypoint {index} is invalid')
            if previous is not None and math.hypot(
                    x - previous['x'], y - previous['y']) > 12.0:
                raise ValueError(f'waypoint segment {index - 1}->{index} is too long')
            waypoint = {'x': x, 'y': y, 'label': label}
            waypoint.update({
                key: item[key] for key in allowed_metadata if key in item})
            validated.append(waypoint)
            previous = waypoint
        return validated

    def pose_callback(self, message):
        q = message.pose.pose.orientation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        self.pose = (
            message.pose.pose.position.x,
            message.pose.pose.position.y,
            yaw,
        )

    def scan_callback(self, message):
        candidates = []
        angle = message.angle_min
        for distance in message.ranges:
            if abs(angle) <= math.radians(32.0) and math.isfinite(distance):
                if message.range_min <= distance <= message.range_max:
                    candidates.append(distance)
            angle += message.angle_increment
        self.front_clearance = min(candidates, default=math.inf)

    def publish_stop(self):
        self.cmd_pub.publish(Twist())

    def control_step(self):
        now = self.timestamp()
        if not self.active or self.finished or self.pose is None:
            self.publish_navigation_status(now)
            return

        elapsed = (self.get_clock().now() - self.start_time).nanoseconds / 1e9
        if elapsed < self.activation_delay:
            self.publish_stop()
            self.publish_navigation_status(now)
            return

        target = self.waypoints[self.index]
        dx = float(target['x']) - self.pose[0]
        dy = float(target['y']) - self.pose[1]
        distance = math.hypot(dx, dy)

        if distance <= self.goal_tolerance:
            label = target.get('label', f'waypoint_{self.index}')
            self.get_logger().info(
                f'Reached {self.index + 1}/{len(self.waypoints)}: {label}')
            self.publish_event(
                'waypoint_reached',
                label=label,
                index=self.index + 1,
                total=len(self.waypoints),
                mission_phase=target.get('mission_phase'),
            )
            self.index += 1
            if self.index >= len(self.waypoints):
                if self.loop:
                    self.index = 0
                    self.get_logger().info(f'Restarting route {self.route_name!r}')
                else:
                    self.finished = True
                    self.active = False
                    self.publish_stop()
                    self.publish_event('route_completed')
                    self.get_logger().info(f'Completed route {self.route_name!r}')
                self.publish_navigation_status(now)
                return
            target = self.waypoints[self.index]
            dx = float(target['x']) - self.pose[0]
            dy = float(target['y']) - self.pose[1]
            distance = math.hypot(dx, dy)

        heading = math.atan2(dy, dx)
        heading_error = normalize_angle(heading - self.pose[2])

        command = Twist()
        command.angular.z = max(
            -self.max_angular,
            min(self.max_angular, 2.0 * heading_error),
        )

        if abs(heading_error) <= self.heading_tolerance:
            speed_scale = max(0.20, 1.0 - abs(heading_error) / self.heading_tolerance)
            command.linear.x = min(self.max_linear, 0.65 * distance) * speed_scale

        obstructed = (
            self.front_clearance < self.stop_distance
            and command.linear.x > 0.0
        )
        if obstructed:
            command.linear.x = 0.0
            command.angular.z = 0.0
            if not self.blocked:
                self.blocked = True
                self.blocked_since = now
                self.block_count += 1
                self.publish_event(
                    'blocked', clearance=self.front_clearance,
                    block_count=self.block_count,
                    blocked_since_sec=self.blocked_since)
                self.get_logger().warning(
                    f'Blocked at {self.front_clearance:.2f} m')
        elif self.blocked:
            self.blocked = False
            if self.blocked_since is not None:
                self.last_blocked_duration = max(
                    0.0, now - self.blocked_since)
            self.blocked_since = None
            self.publish_event(
                'obstacle_cleared', clearance=self.front_clearance,
                block_count=self.block_count,
                last_blocked_duration_sec=self.last_blocked_duration)
            self.get_logger().info('Front obstacle cleared')

        self.cmd_pub.publish(command)
        self.publish_navigation_status(now)


def main(args=None):
    rclpy.init(args=args)
    node = WaypointFollower()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if rclpy.ok():
                node.publish_stop()
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except (Exception, KeyboardInterrupt):
            # Launch may forward a second signal while shutdown is in progress.
            pass


if __name__ == '__main__':
    main()
