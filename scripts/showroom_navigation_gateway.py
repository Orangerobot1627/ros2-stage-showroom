#!/usr/bin/env python3
"""ROS gateway from semantic navigation requests to Stage or Nav2 plans."""

import json
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from showroom_navigation import (
    build_delivery_plan,
    build_guide_plan,
    build_temporary_visit_plan,
    GraphRoutePlanner,
    NavigationError,
)
from showroom_task_units import TaskUnitCatalog
from std_msgs.msg import String


class ShowroomNavigationGateway(Node):
    """Own semantic route optimization and isolate navigation backends."""

    def __init__(self):
        super().__init__('showroom_navigation_gateway')
        self.declare_parameter('backend', 'stage_graph')
        self.declare_parameter('graph_file', '')
        self.declare_parameter('routes_file', '')
        self.declare_parameter(
            'request_topic', '/showroom/navigation_requests')
        self.declare_parameter('event_topic', '/showroom/navigation_events')
        self.declare_parameter(
            'route_command_topic', '/showroom/route_commands')
        self.declare_parameter('nav2_plan_topic', '/showroom/nav2_plans')

        self.backend = str(self.get_parameter('backend').value).strip()
        if self.backend not in ('stage_graph', 'nav2'):
            raise ValueError(f'Unsupported navigation backend: {self.backend!r}')
        share = Path(get_package_share_directory('demo_stage'))
        graph_value = str(self.get_parameter('graph_file').value)
        routes_value = str(self.get_parameter('routes_file').value)
        graph_path = (
            Path(graph_value).expanduser() if graph_value
            else share / 'config' / 'navigation_graph.yaml')
        routes_path = (
            Path(routes_value).expanduser() if routes_value
            else share / 'config' / 'routes.yaml')
        self.planner = GraphRoutePlanner.from_files(graph_path, routes_path)
        self.task_catalog = TaskUnitCatalog.from_files(
            share / 'config' / 'task_units.yaml', routes_path)

        reliable = QoSProfile(
            depth=20,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.route_publisher = self.create_publisher(
            String, self.get_parameter('route_command_topic').value, reliable)
        self.nav2_publisher = self.create_publisher(
            String, self.get_parameter('nav2_plan_topic').value, reliable)
        self.event_publisher = self.create_publisher(
            String, self.get_parameter('event_topic').value, reliable)
        self.create_subscription(
            String, self.get_parameter('request_topic').value,
            self.request_callback, reliable)
        self.get_logger().info(
            f'Navigation gateway ready: backend={self.backend}, '
            f'nodes={len(self.planner.nodes)}')

    def publish(self, publisher, document):
        message = String()
        message.data = json.dumps(
            document, ensure_ascii=False, separators=(',', ':'))
        publisher.publish(message)

    def request_callback(self, message):
        mission_id = None
        try:
            request = json.loads(message.data)
            if not isinstance(request, dict):
                raise NavigationError('Navigation request must be an object')
            mission_id = request.get('mission_id')
            request_type = request.get('request_type')
            if request_type == 'delivery':
                plan = build_delivery_plan(self.planner, request)
            elif request_type == 'guide_itinerary':
                plan = build_guide_plan(
                    self.planner, request, self.task_catalog)
            elif request_type == 'temporary_visit':
                plan = build_temporary_visit_plan(
                    self.planner, request, self.task_catalog)
            else:
                raise NavigationError('Unsupported navigation request type')
            if self.backend == 'stage_graph':
                command = dict(plan)
                command.update({
                    'type': 'route_command',
                    'action': 'follow_path',
                })
                self.publish(self.route_publisher, command)
            else:
                self.publish(self.nav2_publisher, plan)
            self.publish(self.event_publisher, {
                'type': 'navigation_planned',
                'backend': self.backend,
                'mission_id': mission_id,
                'robot_id': plan['robot_id'],
                'request_type': plan['request_type'],
                'service_target': plan.get('service_target'),
                'task_ids': plan.get('task_ids'),
                'distance_m': plan['distance_m'],
                'cost': plan['cost'],
                'cost_profile': plan['cost_profile'],
                'waypoint_total': len(plan['waypoints']),
            })
            self.get_logger().info(
                f'Planned {mission_id}: {plan["distance_m"]:.1f} m, '
                f'{len(plan["waypoints"])} waypoints')
        except (json.JSONDecodeError, TypeError, NavigationError) as exception:
            self.publish(self.event_publisher, {
                'type': 'navigation_rejected',
                'backend': self.backend,
                'mission_id': mission_id,
                'reason': str(exception),
            })
            self.get_logger().warning(f'Rejected navigation request: {exception}')


def main(args=None):
    rclpy.init(args=args)
    node = ShowroomNavigationGateway()
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
