#!/usr/bin/env python3
"""Execute semantic showroom delivery stops with Nav2 NavigateToPose."""

import json
import math

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from showroom_navigation import semantic_targets_from_plan
from std_msgs.msg import String


class ShowroomNav2Adapter(Node):
    """Send semantic delivery stops to a namespaced Nav2 action server."""

    def __init__(self):
        super().__init__('showroom_nav2_adapter')
        self.declare_parameter('robot_id', 'robot_1')
        self.declare_parameter('plan_topic', '/showroom/nav2_plans')
        self.declare_parameter('event_topic', '/showroom/robot_events')
        self.declare_parameter(
            'route_command_topic', '/showroom/route_commands')
        self.declare_parameter('action_name', 'navigate_to_pose')
        self.declare_parameter('frame_id', 'map')
        self.declare_parameter('server_wait_timeout_sec', 10.0)
        self.declare_parameter('inter_goal_delay_sec', 1.0)
        self.robot_id = str(self.get_parameter('robot_id').value)
        self.frame_id = str(self.get_parameter('frame_id').value)
        event_qos = QoSProfile(
            depth=20,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.event_publisher = self.create_publisher(
            String, self.get_parameter('event_topic').value, event_qos)
        self.client = ActionClient(
            self, NavigateToPose,
            self.get_parameter('action_name').value)
        self.create_subscription(
            String, self.get_parameter('plan_topic').value,
            self.plan_callback, 10)
        self.create_subscription(
            String, self.get_parameter('route_command_topic').value,
            self.route_command_callback, event_qos)
        self.active_plan = None
        self.targets = []
        self.target_index = 0
        self.inter_goal_timer = None
        self.goal_handle = None
        self.cancel_reason = None
        self.pending_control = None
        self.paused = False
        self.route_started_emitted = False
        self.phase_started_indices = set()
        self.get_logger().info(
            f'Nav2 adapter ready for {self.robot_id}; waiting for action server')

    def publish_event(self, event_type, **fields):
        document = {'type': event_type, 'robot_id': self.robot_id}
        document.update(fields)
        message = String()
        message.data = json.dumps(
            document, ensure_ascii=False, separators=(',', ':'))
        self.event_publisher.publish(message)

    def pose_for_target(self, index):
        target = self.targets[index]
        if index + 1 < len(self.targets):
            reference = self.targets[index + 1]
            yaw = math.atan2(
                reference['y'] - target['y'], reference['x'] - target['x'])
        elif index > 0:
            reference = self.targets[index - 1]
            yaw = math.atan2(
                target['y'] - reference['y'], target['x'] - reference['x'])
        else:
            yaw = 0.0
        pose = PoseStamped()
        pose.header.frame_id = self.frame_id
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = target['x']
        pose.pose.position.y = target['y']
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def plan_callback(self, message):
        try:
            document = json.loads(message.data)
            if document.get('robot_id') != self.robot_id:
                return
            if self.active_plan is not None:
                raise ValueError('Nav2 adapter already has an active plan')
            targets = semantic_targets_from_plan(document)
        except (json.JSONDecodeError, TypeError, ValueError) as exception:
            self.publish_event('route_failed', reason=str(exception))
            return
        if not self.client.wait_for_server(timeout_sec=float(
                self.get_parameter('server_wait_timeout_sec').value)):
            self.publish_event(
                'route_failed', mission_id=document.get('mission_id'),
                reason='NavigateToPose action server unavailable')
            return
        self.active_plan = document
        self.targets = targets
        self.target_index = 0
        self.send_current_target()

    def route_command_callback(self, message):
        """Apply pause, resume and cancel to the active Nav2 mission."""
        document = {}
        try:
            document = json.loads(message.data)
            if document.get('robot_id') != self.robot_id:
                return
            action = document.get('action')
            if action not in ('pause', 'resume', 'cancel'):
                return
            if self.active_plan is None:
                if action == 'cancel':
                    return
                raise ValueError('robot has no active Nav2 mission')
            if action == 'pause':
                self.pause_navigation()
            elif action == 'resume':
                self.resume_navigation()
            else:
                self.cancel_navigation()
        except (json.JSONDecodeError, TypeError, ValueError) as exception:
            self.publish_event(
                'route_command_rejected', action=document.get('action'),
                reason=str(exception), backend='nav2')

    def pause_navigation(self):
        """Cancel motion while retaining the current semantic target."""
        if self.paused or self.cancel_reason == 'pause':
            return
        if self.inter_goal_timer is not None:
            self.cancel_inter_goal_timer()
            self.paused = True
            self.publish_control_event('route_paused')
            return
        if self.goal_handle is None:
            self.pending_control = 'pause'
            return
        self.request_goal_cancel('pause')

    def resume_navigation(self):
        """Replan to the retained target from the robot's current pose."""
        if self.cancel_reason == 'pause':
            self.pending_control = 'resume'
            return
        if not self.paused:
            return
        self.paused = False
        self.pending_control = None
        self.publish_control_event('route_resumed')
        self.send_current_target()

    def cancel_navigation(self):
        """Cancel motion and discard the entire delivery plan."""
        if self.paused:
            self.publish_control_event('route_cancelled')
            self.clear_plan()
            return
        if self.inter_goal_timer is not None:
            self.cancel_inter_goal_timer()
            self.publish_control_event('route_cancelled')
            self.clear_plan()
            return
        if self.goal_handle is None:
            self.pending_control = 'cancel'
            return
        self.request_goal_cancel('cancel')

    def request_goal_cancel(self, reason):
        self.cancel_reason = reason
        future = self.goal_handle.cancel_goal_async()
        future.add_done_callback(self.cancel_response_callback)

    def cancel_response_callback(self, future):
        response = future.result()
        if response is not None and response.goals_canceling:
            return
        reason = self.cancel_reason
        self.cancel_reason = None
        self.publish_event(
            'route_failed', mission_id=self.mission_id(), backend='nav2',
            reason=f'Nav2 rejected {reason} cancellation')
        self.clear_plan()

    def mission_id(self):
        return (self.active_plan or {}).get('mission_id')

    def publish_control_event(self, event_type):
        self.publish_event(
            event_type, mission_id=self.mission_id(), backend='nav2',
            target=self.targets[self.target_index]['label'])

    def send_current_target(self):
        target = self.targets[self.target_index]
        goal = NavigateToPose.Goal()
        goal.pose = self.pose_for_target(self.target_index)
        future = self.client.send_goal_async(goal)
        future.add_done_callback(self.goal_response_callback)
        self.get_logger().info(
            f'Nav2 target {self.target_index + 1}/{len(self.targets)}: '
            f'{target["label"]} ({target["mission_phase"]})')

    def goal_response_callback(self, future):
        goal_handle = future.result()
        document = self.active_plan or {}
        mission_id = document.get('mission_id')
        if not goal_handle.accepted:
            self.publish_event(
                'route_failed', mission_id=mission_id,
                reason='Nav2 rejected NavigateToPose goal')
            self.clear_plan()
            return
        self.goal_handle = goal_handle
        if not self.route_started_emitted:
            self.publish_event(
                'route_started', mission_id=mission_id, backend='nav2')
            self.route_started_emitted = True
        if self.target_index not in self.phase_started_indices:
            if self.targets[self.target_index]['mission_phase'] == 'delivery':
                self.publish_event(
                    'waypoint_reached', mission_id=mission_id,
                    label='depart_pickup', mission_phase='depart_pickup',
                    backend='nav2')
            elif self.targets[self.target_index]['mission_phase'] == 'standby':
                self.publish_event(
                    'waypoint_reached', mission_id=mission_id,
                    label='return_from_delivery', mission_phase='returning',
                    backend='nav2')
            self.phase_started_indices.add(self.target_index)
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.result_callback)
        if self.pending_control in ('pause', 'cancel'):
            control = self.pending_control
            self.pending_control = None
            self.request_goal_cancel(control)

    def result_callback(self, future):
        document = self.active_plan or {}
        mission_id = document.get('mission_id')
        status = future.result().status
        self.goal_handle = None
        if status == GoalStatus.STATUS_CANCELED:
            reason = self.cancel_reason
            self.cancel_reason = None
            if reason == 'pause':
                self.paused = True
                self.publish_control_event('route_paused')
                if self.pending_control == 'resume':
                    self.pending_control = None
                    self.resume_navigation()
                return
            if reason == 'cancel':
                self.publish_control_event('route_cancelled')
                self.clear_plan()
                return
        if status != GoalStatus.STATUS_SUCCEEDED:
            self.publish_event(
                'route_failed', mission_id=mission_id, backend='nav2',
                reason=f'NavigateToPose status={status}',
                target=self.targets[self.target_index]['label'])
            self.clear_plan()
            return

        target = self.targets[self.target_index]
        self.publish_event(
            'waypoint_reached', mission_id=mission_id, backend='nav2',
            label=target['label'], mission_phase=target['mission_phase'],
            index=self.target_index + 1, total=len(self.targets))
        self.target_index += 1
        if self.target_index < len(self.targets):
            delay = float(self.get_parameter('inter_goal_delay_sec').value)
            self.inter_goal_timer = self.create_timer(
                max(0.1, delay), self.send_delayed_target)
            return

        self.publish_event(
            'route_completed', mission_id=mission_id, backend='nav2',
            service_target=document.get('service_target'))
        self.clear_plan()

    def send_delayed_target(self):
        """Start the next leg after Nav2 has finished the previous action."""
        self.cancel_inter_goal_timer()
        if self.active_plan is not None and not self.paused:
            self.send_current_target()

    def cancel_inter_goal_timer(self):
        if self.inter_goal_timer is not None:
            self.inter_goal_timer.cancel()
            self.destroy_timer(self.inter_goal_timer)
            self.inter_goal_timer = None

    def clear_plan(self):
        self.cancel_inter_goal_timer()
        self.active_plan = None
        self.targets = []
        self.target_index = 0
        self.goal_handle = None
        self.cancel_reason = None
        self.pending_control = None
        self.paused = False
        self.route_started_emitted = False
        self.phase_started_indices.clear()


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
