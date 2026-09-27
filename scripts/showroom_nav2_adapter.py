#!/usr/bin/env python3
"""Optional Nav2 NavigateThroughPoses adapter for optimized showroom plans."""

import json
import math

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateThroughPoses
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String


class ShowroomNav2Adapter(Node):
    """Send gateway paths to a namespaced Nav2 action server."""

    def __init__(self):
        super().__init__('showroom_nav2_adapter')
        self.declare_parameter('robot_id', 'robot_1')
        self.declare_parameter('plan_topic', '/showroom/nav2_plans')
        self.declare_parameter('event_topic', '/showroom/robot_events')
        self.declare_parameter('action_name', 'navigate_through_poses')
        self.declare_parameter('frame_id', 'map')
        self.robot_id = str(self.get_parameter('robot_id').value)
        self.frame_id = str(self.get_parameter('frame_id').value)
        self.event_publisher = self.create_publisher(
            String, self.get_parameter('event_topic').value, 20)
        self.client = ActionClient(
            self, NavigateThroughPoses,
            self.get_parameter('action_name').value)
        self.create_subscription(
            String, self.get_parameter('plan_topic').value,
            self.plan_callback, 10)
        self.active_plan = None
        self.get_logger().info(
            f'Nav2 adapter ready for {self.robot_id}; waiting for action server')

    def publish_event(self, event_type, **fields):
        document = {'type': event_type, 'robot_id': self.robot_id}
        document.update(fields)
        message = String()
        message.data = json.dumps(
            document, ensure_ascii=False, separators=(',', ':'))
        self.event_publisher.publish(message)

    def poses_from_plan(self, document):
        waypoints = document.get('waypoints') or []
        if not waypoints or len(waypoints) > 256:
            raise ValueError('Nav2 plan needs 1..256 waypoints')
        poses = []
        for index, item in enumerate(waypoints):
            x = float(item['x'])
            y = float(item['y'])
            next_item = waypoints[min(index + 1, len(waypoints) - 1)]
            yaw = math.atan2(float(next_item['y']) - y, float(next_item['x']) - x)
            pose = PoseStamped()
            pose.header.frame_id = self.frame_id
            pose.header.stamp = self.get_clock().now().to_msg()
            pose.pose.position.x = x
            pose.pose.position.y = y
            pose.pose.orientation.z = math.sin(yaw / 2.0)
            pose.pose.orientation.w = math.cos(yaw / 2.0)
            poses.append(pose)
        return poses

    def plan_callback(self, message):
        try:
            document = json.loads(message.data)
            if document.get('robot_id') != self.robot_id:
                return
            if self.active_plan is not None:
                raise ValueError('Nav2 adapter already has an active plan')
            poses = self.poses_from_plan(document)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exception:
            self.publish_event('route_failed', reason=str(exception))
            return
        if not self.client.wait_for_server(timeout_sec=0.2):
            self.publish_event(
                'route_failed', mission_id=document.get('mission_id'),
                reason='NavigateThroughPoses action server unavailable')
            return
        goal = NavigateThroughPoses.Goal()
        goal.poses = poses
        self.active_plan = document
        future = self.client.send_goal_async(goal)
        future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        mission_id = self.active_plan.get('mission_id')
        if not goal_handle.accepted:
            self.publish_event(
                'route_failed', mission_id=mission_id,
                reason='Nav2 rejected NavigateThroughPoses goal')
            self.active_plan = None
            return
        self.publish_event('route_started', mission_id=mission_id, backend='nav2')
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.result_callback)

    def result_callback(self, future):
        document = self.active_plan or {}
        mission_id = document.get('mission_id')
        status = future.result().status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.publish_event(
                'route_completed', mission_id=mission_id, backend='nav2',
                service_target=document.get('service_target'))
        else:
            self.publish_event(
                'route_failed', mission_id=mission_id, backend='nav2',
                reason=f'NavigateThroughPoses status={status}')
        self.active_plan = None


def main(args=None):
    rclpy.init(args=args)
    node = ShowroomNav2Adapter()
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
