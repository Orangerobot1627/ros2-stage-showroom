#!/usr/bin/env python3
"""Deterministic tests for obstacle and recovery monitoring state."""

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_monitor import RobotState  # noqa: E402


def load_session_tool():
    path = ROOT / 'tools' / 'showroom_session.py'
    specification = importlib.util.spec_from_file_location(
        'showroom_session_for_test', path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def main():
    robot = RobotState('robot_0')
    robot.handle_event({
        'type': 'route_started',
        'robot_id': 'robot_0',
        'route': 'guide_full_route',
        'total': 65,
        'stamp': 10.0,
    }, 10.0)
    assert robot.snapshot(10.0)['waypoint_total'] == 65
    robot.handle_event({
        'type': 'waypoint_reached',
        'robot_id': 'robot_0',
        'label': 'stairs_clearance',
        'index': 2,
        'total': 65,
        'stamp': 15.0,
    }, 15.0)
    robot.handle_event({
        'type': 'blocked',
        'robot_id': 'robot_0',
        'stamp': 20.0,
    }, 20.0)

    blocked = robot.snapshot(25.0)
    assert blocked['navigation_state'] == 'BLOCKED'
    assert blocked['current_waypoint'] == 'stairs_clearance'
    assert blocked['blocked_duration_sec'] == 5.0
    assert blocked['recovery_state'] == 'WAITING_FOR_CLEARANCE'
    assert blocked['block_count'] == 1

    robot.handle_event({
        'type': 'obstacle_cleared',
        'robot_id': 'robot_0',
        'stamp': 27.0,
    }, 27.0)
    resumed = robot.snapshot(28.0)
    assert resumed['navigation_state'] == 'NAVIGATING'
    assert resumed['obstacle_detected'] is False
    assert resumed['blocked_duration_sec'] == 0.0
    assert resumed['last_blocked_duration_sec'] == 7.0
    assert resumed['recovery_state'] == 'RESUMED_AFTER_CLEARANCE'
    assert resumed['mission_elapsed_sec'] == 18.0

    heartbeat_robot = RobotState('robot_1')
    heartbeat_robot.handle_event({
        'type': 'route_started',
        'route': 'coffee_delivery_route',
        'stamp': 30.0,
    }, 30.0)
    heartbeat_robot.handle_navigation_status({
        'route': 'coffee_delivery_route',
        'active': True,
        'finished': False,
        'blocked': True,
        'blocked_since_sec': 35.0,
        'blocked_duration_sec': 5.0,
        'last_blocked_duration_sec': 2.5,
        'block_count': 2,
        'front_clearance_m': 0.42,
        'action_feedback': {
            'action_active': True,
            'navigation_time_sec': 4.0,
            'estimated_time_remaining_sec': 8.5,
            'distance_remaining_m': 3.25,
            'number_of_recoveries': 1,
            'target_recoveries': 1,
            'feedback_age_sec': 0.05,
        },
    }, 40.0)
    heartbeat_blocked = heartbeat_robot.snapshot(40.0)
    assert heartbeat_blocked['navigation_state'] == 'BLOCKED'
    assert heartbeat_blocked['blocked_duration_sec'] == 5.0
    assert heartbeat_blocked['block_count'] == 2
    assert heartbeat_blocked['front_clearance_m'] == 0.42
    assert heartbeat_blocked['nav2_feedback']['distance_remaining_m'] == 3.25
    assert heartbeat_blocked['nav2_feedback'][
        'estimated_time_remaining_sec'] == 8.5
    heartbeat_robot.handle_navigation_status({
        'active': True,
        'finished': False,
        'blocked': False,
        'last_blocked_duration_sec': 6.25,
        'block_count': 2,
    }, 41.25)
    heartbeat_resumed = heartbeat_robot.snapshot(41.25)
    assert heartbeat_resumed['navigation_state'] == 'NAVIGATING'
    assert heartbeat_resumed['last_blocked_duration_sec'] == 6.25
    assert heartbeat_resumed['recovery_state'] == 'RESUMED_AFTER_CLEARANCE'

    session_tool = load_session_tool()
    assert session_tool.format_duration(233.8) == '00:03:53.800'
    dashboard = session_tool.render_monitor({
        'sequence': 42,
        'published_at': '2026-09-26T10:20:30.123+08:00',
        'sim_time_sec': 233.8,
        'business': {
            'guide_state': 'TOURING',
            'coffee_state': 'STANDBY',
            'coffee_trigger': 'tunnel_center_south',
            'coffee_trigger_reached': False,
        },
        'robots': {
            'robot_0': resumed,
            'robot_1': heartbeat_resumed,
        },
    }, {'session_id': 'test-session', 'domain_id': 81})
    assert '科技展馆双机器人运行监控' in dashboard
    assert '仿真时间 00:03:53.800' in dashboard
    assert '数据序号 42' in dashboard
    assert '蓝色导览机器人: 正在导航' in dashboard
    assert '障碍已清除，导航已继续' in dashboard
    assert 'Nav2进度: 距当前目标 3.25 m' in dashboard
    assert '恢复 1 次' in dashboard
    assert '配送触发点=时空隧道南段（未到达）' in dashboard

    parser = session_tool.build_parser()
    start = parser.parse_args(['start', '--monitor-windows'])
    assert start.monitor_windows is True
    assert start.monitor_lead_sec == 1.0
    voice = parser.parse_args([
        'start', '--voice', '--voice-rms-threshold', '150.0'])
    assert voice.voice is True
    assert voice.voice_rms_threshold == 150.0
    voice_arguments = session_tool.apply_voice_launch_arguments(
        [], enabled=True, rms_threshold=None)
    assert 'enable_llm:=true' in voice_arguments
    assert 'enable_voice:=true' in voice_arguments
    assert 'voice_rms_threshold:=150.0' in voice_arguments
    overridden_voice_arguments = session_tool.apply_voice_launch_arguments(
        ['voice_rms_threshold:=180'], enabled=True, rms_threshold=120.0)
    assert 'voice_rms_threshold:=120.0' in overridden_voice_arguments
    assert 'voice_rms_threshold:=180' not in overridden_voice_arguments
    prelaunch = parser.parse_args([
        'monitor', '--domain', '88', '--session-id', 'test-session',
        '--parent-pid', '123',
    ])
    assert prelaunch.domain == 88
    detail = parser.parse_args(['detail-monitor', '--interval', '0.1'])
    assert detail.interval == 0.1

    print('Monitor obstacle and recovery state: OK')


if __name__ == '__main__':
    main()
