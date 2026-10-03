#!/usr/bin/env python3
"""Publish one aggregated operational view of the showroom simulation."""

import datetime as dt
import json
import math

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    qos_profile_sensor_data,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String


class RobotState:
    """Accumulate telemetry and route events for one robot."""

    def __init__(self, robot_id):
        self.robot_id = robot_id
        self.navigation_state = 'WAITING'
        self.route = None
        self.current_waypoint = None
        self.waypoint_index = 0
        self.waypoint_total = 0
        self.pose = None
        self.linear_speed = 0.0
        self.angular_speed = 0.0
        self.front_clearance = math.inf
        self.obstacle_detected = False
        self.blocked_since = None
        self.last_blocked_duration = 0.0
        self.block_count = 0
        self.recovery_state = 'READY'
        self.mission_started_at = None
        self.last_event = None
        self.local_planner = {
            'state': 'TRACKING', 'active': False,
            'avoidance_count': 0,
        }
        self.nav2_feedback = {
            'action_active': False,
            'navigation_time_sec': None,
            'estimated_time_remaining_sec': None,
            'distance_remaining_m': None,
            'number_of_recoveries': 0,
            'target_recoveries': 0,
            'feedback_age_sec': None,
        }

    @staticmethod
    def event_time(event, fallback):
        stamp = event.get('stamp', fallback)
        if isinstance(stamp, (int, float)):
            return float(stamp)
        return fallback

    def handle_event(self, event, now):
        """Apply one route event to the operational state."""
        event_type = event.get('type')
        stamp = self.event_time(event, now)
        self.last_event = event_type
        self.route = event.get('route', self.route)

        if event_type == 'route_started':
            self.navigation_state = 'NAVIGATING'
            self.recovery_state = 'READY'
            self.mission_started_at = stamp
            self.current_waypoint = None
            self.waypoint_index = 0
            self.waypoint_total = int(event.get('total', 0))
        elif event_type == 'waypoint_reached':
            self.navigation_state = 'NAVIGATING'
            self.current_waypoint = event.get('label')
            self.waypoint_index = int(event.get('index', 0))
            self.waypoint_total = int(event.get('total', 0))
        elif event_type == 'blocked':
            self.navigation_state = 'BLOCKED'
            self.obstacle_detected = True
            if self.blocked_since is None:
                self.blocked_since = stamp
                self.block_count += 1
            if isinstance(event.get('block_count'), int):
                self.block_count = max(
                    self.block_count, event['block_count'])
            self.recovery_state = 'WAITING_FOR_CLEARANCE'
        elif event_type == 'obstacle_cleared':
            if self.blocked_since is not None:
                self.last_blocked_duration = max(
                    0.0, stamp - self.blocked_since)
            self.blocked_since = None
            if isinstance(event.get('last_blocked_duration_sec'),
                          (int, float)):
                self.last_blocked_duration = max(
                    0.0, float(event['last_blocked_duration_sec']))
            self.obstacle_detected = False
            self.navigation_state = 'NAVIGATING'
            self.recovery_state = 'RESUMED_AFTER_CLEARANCE'
        elif event_type == 'avoidance_started':
            self.navigation_state = 'AVOIDING'
            self.obstacle_detected = True
            self.recovery_state = 'LOCAL_BYPASS'
            self.local_planner = event.get(
                'local_planner', self.local_planner)
        elif event_type == 'obstacle_bypassed':
            self.navigation_state = 'NAVIGATING'
            self.obstacle_detected = False
            self.recovery_state = 'REJOINED_ROUTE'
            self.local_planner = event.get(
                'local_planner', self.local_planner)
        elif event_type == 'route_paused':
            self.navigation_state = 'PAUSED'
        elif event_type == 'route_resumed':
            self.navigation_state = 'NAVIGATING'
        elif event_type == 'route_completed':
            self.navigation_state = 'COMPLETED'
            self.linear_speed = 0.0
            self.angular_speed = 0.0
        elif event_type == 'route_cancelled':
            self.navigation_state = 'CANCELLED'
            self.linear_speed = 0.0
            self.angular_speed = 0.0

    def handle_navigation_status(self, status, now):
        """Reconcile state from the route follower's durable heartbeat."""
        self.route = status.get('route', self.route)
        count = status.get('block_count')
        if isinstance(count, int):
            self.block_count = max(0, count)
        last_duration = status.get('last_blocked_duration_sec')
        if isinstance(last_duration, (int, float)):
            self.last_blocked_duration = max(0.0, float(last_duration))
        clearance = status.get('front_clearance_m')
        if isinstance(clearance, (int, float)):
            self.front_clearance = float(clearance)
        local_planner = status.get('local_planner')
        if isinstance(local_planner, dict):
            self.local_planner = local_planner
        action_feedback = status.get('action_feedback')
        if isinstance(action_feedback, dict):
            self.nav2_feedback = {
                key: action_feedback.get(key, default)
                for key, default in self.nav2_feedback.items()
            }

        was_blocked = self.navigation_state == 'BLOCKED'
        if status.get('blocked'):
            blocked_since = status.get('blocked_since_sec')
            if isinstance(blocked_since, (int, float)):
                self.blocked_since = float(blocked_since)
            elif self.blocked_since is None:
                duration = status.get('blocked_duration_sec', 0.0)
                self.blocked_since = now - max(0.0, float(duration))
            self.navigation_state = 'BLOCKED'
            self.obstacle_detected = True
            self.recovery_state = 'WAITING_FOR_CLEARANCE'
            self.last_event = 'navigation_status:blocked'
        elif status.get('finished'):
            self.blocked_since = None
            self.navigation_state = 'COMPLETED'
            self.obstacle_detected = False
        elif status.get('active'):
            self.blocked_since = None
            self.navigation_state = (
                'AVOIDING' if self.local_planner.get('active')
                else 'NAVIGATING')
            if self.local_planner.get('active'):
                self.obstacle_detected = True
                self.recovery_state = 'LOCAL_BYPASS'
            if was_blocked:
                self.recovery_state = 'RESUMED_AFTER_CLEARANCE'
                self.last_event = 'navigation_status:cleared'

    def snapshot(self, now):
        """Return a JSON-compatible point-in-time snapshot."""
        blocked_duration = 0.0
        if self.blocked_since is not None:
            blocked_duration = max(0.0, now - self.blocked_since)
        mission_elapsed = None
        if self.mission_started_at is not None:
            mission_elapsed = max(0.0, now - self.mission_started_at)
        clearance = None
        if math.isfinite(self.front_clearance):
            clearance = round(self.front_clearance, 3)

        return {
            'navigation_state': self.navigation_state,
            'route': self.route,
            'current_waypoint': self.current_waypoint,
            'waypoint_index': self.waypoint_index,
            'waypoint_total': self.waypoint_total,
            'mission_elapsed_sec': (
                None if mission_elapsed is None else round(mission_elapsed, 3)),
            'pose': self.pose,
            'command_velocity': {
                'linear_x': round(self.linear_speed, 3),
                'angular_z': round(self.angular_speed, 3),
            },
            'front_clearance_m': clearance,
            'obstacle_detected': self.obstacle_detected,
            'blocked_duration_sec': round(blocked_duration, 3),
            'last_blocked_duration_sec': round(
                self.last_blocked_duration, 3),
            'block_count': self.block_count,
            'recovery_policy': 'LOCAL_BYPASS_THEN_STOP_IF_UNSAFE',
            'recovery_state': self.recovery_state,
            'local_planner': self.local_planner,
            'nav2_feedback': self.nav2_feedback,
            'last_event': self.last_event,
        }


class ShowroomMonitor(Node):
    """Aggregate business, route, pose, velocity, and LiDAR state."""

    def __init__(self):
        super().__init__('showroom_monitor')
        self.declare_parameter('publish_period_sec', 0.1)
        self.declare_parameter('front_sector_deg', 32.0)
        self.declare_parameter('guide_stop_distance', 0.60)
        self.declare_parameter('coffee_stop_distance', 0.65)

        self.front_sector = math.radians(
            float(self.get_parameter('front_sector_deg').value))
        self.stop_distances = {
            'robot_0': float(
                self.get_parameter('guide_stop_distance').value),
            'robot_1': float(
                self.get_parameter('coffee_stop_distance').value),
        }
        self.robots = {
            robot_id: RobotState(robot_id)
            for robot_id in ('robot_0', 'robot_1')
        }
        self.business = {}
        self.sequence = 0

        output_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        navigation_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.monitor_publisher = self.create_publisher(
            String, '/showroom/monitor', output_qos)
        self.create_subscription(
            String, '/showroom/status', self.status_callback, output_qos)
        self.create_subscription(
            String, '/showroom/robot_events',
            self.event_callback, navigation_qos)
        self.create_subscription(
            String, '/showroom/navigation_status',
            self.navigation_status_callback, navigation_qos)

        for robot_id in self.robots:
            self.create_subscription(
                Odometry,
                f'/{robot_id}/ground_truth',
                lambda message, rid=robot_id: self.pose_callback(message, rid),
                10,
            )
            self.create_subscription(
                Twist,
                f'/{robot_id}/cmd_vel',
                lambda message, rid=robot_id: self.velocity_callback(
                    message, rid),
                10,
            )
            self.create_subscription(
                LaserScan,
                f'/{robot_id}/base_scan',
                lambda message, rid=robot_id: self.scan_callback(message, rid),
                qos_profile_sensor_data,
            )

        period = float(self.get_parameter('publish_period_sec').value)
        self.wall_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.create_timer(
            period, self.publish_monitor, clock=self.wall_clock)
        self.get_logger().info(
            'Publishing aggregated state on /showroom/monitor')

    def simulation_time(self):
        return self.get_clock().now().nanoseconds / 1e9

    @staticmethod
    def parse_json(message):
        document = json.loads(message.data)
        if not isinstance(document, dict):
            raise ValueError('JSON payload must be an object')
        return document

    def status_callback(self, message):
        try:
            self.business = self.parse_json(message)
        except (json.JSONDecodeError, TypeError, ValueError) as exception:
            self.get_logger().warning(
                f'Ignored malformed business status: {exception}')

    def event_callback(self, message):
        try:
            event = self.parse_json(message)
            robot = self.robots.get(event.get('robot_id'))
            if robot is None:
                return
            robot.handle_event(event, self.simulation_time())
            if event.get('type') == 'blocked':
                self.get_logger().warning(
                    f'{robot.robot_id} blocked; waiting for clearance')
            elif event.get('type') == 'obstacle_cleared':
                self.get_logger().info(
                    f'{robot.robot_id} obstacle cleared; navigation resumed')
        except (json.JSONDecodeError, TypeError, ValueError) as exception:
            self.get_logger().warning(
                f'Ignored malformed robot event: {exception}')

    def navigation_status_callback(self, message):
        try:
            status = self.parse_json(message)
            robot = self.robots.get(status.get('robot_id'))
            if robot is None:
                return
            robot.handle_navigation_status(status, self.simulation_time())
        except (json.JSONDecodeError, TypeError, ValueError) as exception:
            self.get_logger().warning(
                f'Ignored malformed navigation status: {exception}')

    def pose_callback(self, message, robot_id):
        position = message.pose.pose.position
        orientation = message.pose.pose.orientation
        yaw = math.atan2(
            2.0 * (orientation.w * orientation.z
                   + orientation.x * orientation.y),
            1.0 - 2.0 * (orientation.y * orientation.y
                         + orientation.z * orientation.z),
        )
        self.robots[robot_id].pose = {
            'x': round(position.x, 3),
            'y': round(position.y, 3),
            'yaw_deg': round(math.degrees(yaw), 1),
        }

    def velocity_callback(self, message, robot_id):
        robot = self.robots[robot_id]
        robot.linear_speed = message.linear.x
        robot.angular_speed = message.angular.z

    def scan_callback(self, message, robot_id):
        candidates = []
        angle = message.angle_min
        for distance in message.ranges:
            if abs(angle) <= self.front_sector and math.isfinite(distance):
                if message.range_min <= distance <= message.range_max:
                    candidates.append(distance)
            angle += message.angle_increment
        robot = self.robots[robot_id]
        robot.front_clearance = min(candidates, default=math.inf)
        if robot.navigation_state != 'BLOCKED':
            robot.obstacle_detected = (
                robot.front_clearance < self.stop_distances[robot_id])

    def publish_monitor(self):
        now = self.simulation_time()
        self.sequence += 1
        document = {
            'type': 'showroom_monitor',
            'sequence': self.sequence,
            'sim_time_sec': round(now, 3),
            'published_at': dt.datetime.now().astimezone().isoformat(
                timespec='milliseconds'),
            'business': self.business,
            'robots': {
                robot_id: robot.snapshot(now)
                for robot_id, robot in self.robots.items()
            },
        }
        message = String()
        message.data = json.dumps(
            document, ensure_ascii=False, separators=(',', ':'))
        self.monitor_publisher.publish(message)


def main(args=None):
    rclpy.init(args=args)
    node = ShowroomMonitor()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except (Exception, KeyboardInterrupt):
            # Launch can forward another signal while cleanup is in progress.
            pass


if __name__ == '__main__':
    main()
