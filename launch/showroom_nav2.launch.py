#!/usr/bin/env python3
"""Stage showroom with one isolated Nav2 stack for each robot."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode, ParameterFile
from nav2_common.launch import RewrittenYaml


NAV2_LIFECYCLE_NODES = [
    'map_server',
    'controller_server',
    'planner_server',
    'behavior_server',
    'bt_navigator',
    'velocity_smoother',
    'collision_monitor',
]


def rewritten_robot_params(params_file, map_file, bt_file, robot_id, pose):
    """Bind the shared Nav2 template to one Stage robot's TF frames."""
    return ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            root_key=robot_id,
            param_rewrites={
                'map_server.ros__parameters.yaml_filename': map_file,
                'base_frame_id': f'{robot_id}/base_link',
                'odom_frame_id': f'{robot_id}/odom',
                'robot_base_frame': f'{robot_id}/base_link',
                'default_nav_to_pose_bt_xml': bt_file,
                'local_frame': f'{robot_id}/odom',
                'local_costmap.local_costmap.ros__parameters.global_frame': (
                    f'{robot_id}/odom'),
                'amcl.ros__parameters.initial_pose.x': str(pose['x']),
                'amcl.ros__parameters.initial_pose.y': str(pose['y']),
                'amcl.ros__parameters.initial_pose.yaw': str(pose['yaw']),
            },
            convert_types=True,
        ),
        allow_substs=True,
    )


def nav2_components(robot_id, robot_params):
    """Create a complete namespaced navigation pipeline for one robot."""
    return [
        ComposableNode(
            package='nav2_map_server',
            plugin='nav2_map_server::MapServer',
            name='map_server',
            namespace=robot_id,
            parameters=[robot_params]),
        ComposableNode(
            package='nav2_controller',
            plugin='nav2_controller::ControllerServer',
            name='controller_server',
            namespace=robot_id,
            parameters=[robot_params],
            remappings=[('cmd_vel', 'cmd_vel_nav')]),
        ComposableNode(
            package='nav2_planner',
            plugin='nav2_planner::PlannerServer',
            name='planner_server',
            namespace=robot_id,
            parameters=[robot_params]),
        ComposableNode(
            package='nav2_behaviors',
            plugin='behavior_server::BehaviorServer',
            name='behavior_server',
            namespace=robot_id,
            parameters=[robot_params],
            remappings=[('cmd_vel', 'cmd_vel_nav')]),
        ComposableNode(
            package='nav2_bt_navigator',
            plugin='nav2_bt_navigator::BtNavigator',
            name='bt_navigator',
            namespace=robot_id,
            parameters=[robot_params]),
        ComposableNode(
            package='nav2_velocity_smoother',
            plugin='nav2_velocity_smoother::VelocitySmoother',
            name='velocity_smoother',
            namespace=robot_id,
            parameters=[robot_params],
            remappings=[('cmd_vel', 'cmd_vel_nav')]),
        ComposableNode(
            package='nav2_collision_monitor',
            plugin='nav2_collision_monitor::CollisionMonitor',
            name='collision_monitor',
            namespace=robot_id,
            parameters=[robot_params]),
        ComposableNode(
            package='nav2_lifecycle_manager',
            plugin='nav2_lifecycle_manager::LifecycleManager',
            name='lifecycle_manager_navigation',
            namespace=robot_id,
            parameters=[{
                'use_sim_time': True,
                'autostart': True,
                'bond_timeout': 4.0,
                'node_names': NAV2_LIFECYCLE_NODES,
            }]),
    ]


def robot_nav2_actions(robot_id, pose, params_file, map_file, bt_file,
                       ros_domain_id):
    """Create deterministic Stage localization and one Nav2 container."""
    robot_params = rewritten_robot_params(
        params_file, map_file, bt_file, robot_id, pose)
    environment = {
        'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
        'ROS_DOMAIN_ID': ros_domain_id,
    }
    return [
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name=f'{robot_id}_stage_localization',
            arguments=[
                '--x', str(pose['x']), '--y', str(pose['y']), '--z', '0.0',
                '--yaw', str(pose['yaw']),
                '--pitch', '0.0', '--roll', '0.0',
                '--frame-id', 'map',
                '--child-frame-id', f'{robot_id}/odom',
            ],
            additional_env=environment,
        ),
        ComposableNodeContainer(
            namespace=robot_id,
            name='nav2_container',
            package='rclcpp_components',
            executable='component_container_isolated',
            output='screen',
            parameters=[robot_params],
            additional_env={
                **environment,
                'RCUTILS_LOGGING_BUFFERED_STREAM': '1',
                'PYTHONPATH': EnvironmentVariable(
                    'PYTHONPATH', default_value=''),
            },
            composable_node_descriptions=nav2_components(
                robot_id, robot_params),
        ),
    ]


def generate_launch_description():
    share = get_package_share_directory('demo_stage')
    base_launch = os.path.join(share, 'launch', 'showroom.launch.py')
    map_file = os.path.join(share, 'map', 'showroom_final.yaml')
    params_file = os.path.join(share, 'config', 'nav2_stage_params.yaml')
    world_file = os.path.join(share, 'world', 'showroom_nav2.world')
    bt_file = os.path.join(
        get_package_share_directory('nav2_bt_navigator'),
        'behavior_trees', 'navigate_to_pose_w_replanning_and_recovery.xml')

    enable_gui = LaunchConfiguration('enable_gui')
    business_auto_start = LaunchConfiguration('business_auto_start')
    enable_llm = LaunchConfiguration('enable_llm')
    enable_voice = LaunchConfiguration('enable_voice')
    voice_rms_threshold = LaunchConfiguration('voice_rms_threshold')
    ros_domain_id = LaunchConfiguration('ros_domain_id')
    robots = {
        'robot_0': {'x': 0.0, 'y': -14.5, 'yaw': 1.57079632679},
        'robot_1': {'x': 2.3, 'y': -14.5, 'yaw': 1.57079632679},
    }

    actions = [
        DeclareLaunchArgument('enable_gui', default_value='true'),
        DeclareLaunchArgument('business_auto_start', default_value='false'),
        DeclareLaunchArgument('enable_llm', default_value='false'),
        DeclareLaunchArgument('enable_voice', default_value='false'),
        DeclareLaunchArgument('voice_rms_threshold', default_value='250.0'),
        DeclareLaunchArgument('ros_domain_id', default_value='81'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(base_launch),
            launch_arguments={
                'enable_gui': enable_gui,
                'world_file': world_file,
                'auto_drive': 'true',
                'business_mode': 'true',
                'business_auto_start': business_auto_start,
                'enable_llm': enable_llm,
                'enable_voice': enable_voice,
                'voice_rms_threshold': voice_rms_threshold,
                'navigation_backend': 'nav2',
                'base_watchdog_timeout_sec': '3.0',
                'one_tf_tree': 'true',
                'ros_domain_id': ros_domain_id,
            }.items(),
        ),
    ]
    # Stage publishes each odom->base_link transform from a known spawn pose.
    # Fixed map->odom transforms keep accelerated simulation deterministic.
    for robot_id, pose in robots.items():
        actions.extend(robot_nav2_actions(
            robot_id, pose, params_file, map_file, bt_file, ros_domain_id))
    return LaunchDescription(actions)
