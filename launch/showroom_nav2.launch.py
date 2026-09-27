#!/usr/bin/env python3
"""Stage showroom with a lightweight namespaced Nav2 service-robot stack."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode, ParameterFile
from nav2_common.launch import RewrittenYaml


def generate_launch_description():
    share = get_package_share_directory('demo_stage')
    base_launch = os.path.join(share, 'launch', 'showroom.launch.py')
    map_file = os.path.join(share, 'map', 'showroom_final.yaml')
    params_file = os.path.join(share, 'config', 'nav2_stage_params.yaml')

    enable_gui = LaunchConfiguration('enable_gui')
    business_auto_start = LaunchConfiguration('business_auto_start')
    enable_llm = LaunchConfiguration('enable_llm')
    enable_voice = LaunchConfiguration('enable_voice')
    ros_domain_id = LaunchConfiguration('ros_domain_id')

    robot_params = ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            root_key='robot_1',
            param_rewrites={
                'map_server.ros__parameters.yaml_filename': map_file,
            },
            convert_types=True,
        ),
        allow_substs=True,
    )
    # Stage's shared TF topic carries uniquely prefixed frames for both robots.
    # The Nav2 parameters select robot_1/odom and robot_1/base_link explicitly.
    tf_remaps = []
    components = [
        ComposableNode(
            package='nav2_map_server',
            plugin='nav2_map_server::MapServer',
            name='map_server',
            namespace='robot_1',
            parameters=[robot_params],
            remappings=tf_remaps),
        ComposableNode(
            package='nav2_controller',
            plugin='nav2_controller::ControllerServer',
            name='controller_server',
            namespace='robot_1',
            parameters=[robot_params],
            remappings=tf_remaps + [('cmd_vel', 'cmd_vel_nav')]),
        ComposableNode(
            package='nav2_planner',
            plugin='nav2_planner::PlannerServer',
            name='planner_server',
            namespace='robot_1',
            parameters=[robot_params],
            remappings=tf_remaps),
        ComposableNode(
            package='nav2_behaviors',
            plugin='behavior_server::BehaviorServer',
            name='behavior_server',
            namespace='robot_1',
            parameters=[robot_params],
            remappings=tf_remaps + [('cmd_vel', 'cmd_vel_nav')]),
        ComposableNode(
            package='nav2_bt_navigator',
            plugin='nav2_bt_navigator::BtNavigator',
            name='bt_navigator',
            namespace='robot_1',
            parameters=[robot_params],
            remappings=tf_remaps),
        ComposableNode(
            package='nav2_velocity_smoother',
            plugin='nav2_velocity_smoother::VelocitySmoother',
            name='velocity_smoother',
            namespace='robot_1',
            parameters=[robot_params],
            remappings=tf_remaps + [('cmd_vel', 'cmd_vel_nav')]),
        ComposableNode(
            package='nav2_collision_monitor',
            plugin='nav2_collision_monitor::CollisionMonitor',
            name='collision_monitor',
            namespace='robot_1',
            parameters=[robot_params],
            remappings=tf_remaps),
        ComposableNode(
            package='nav2_lifecycle_manager',
            plugin='nav2_lifecycle_manager::LifecycleManager',
            name='lifecycle_manager_navigation',
            namespace='robot_1',
            parameters=[{
                'use_sim_time': True,
                'autostart': True,
                'bond_timeout': 4.0,
                'node_names': [
                    'map_server', 'controller_server',
                    'planner_server', 'behavior_server', 'bt_navigator',
                    'velocity_smoother', 'collision_monitor',
                ],
            }]),
    ]

    return LaunchDescription([
        DeclareLaunchArgument('enable_gui', default_value='true'),
        DeclareLaunchArgument('business_auto_start', default_value='false'),
        DeclareLaunchArgument('enable_llm', default_value='false'),
        DeclareLaunchArgument('enable_voice', default_value='false'),
        DeclareLaunchArgument('ros_domain_id', default_value='81'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(base_launch),
            launch_arguments={
                'enable_gui': enable_gui,
                'auto_drive': 'true',
                'business_mode': 'true',
                'business_auto_start': business_auto_start,
                'enable_llm': enable_llm,
                'enable_voice': enable_voice,
                'navigation_backend': 'nav2',
                'one_tf_tree': 'true',
                'ros_domain_id': ros_domain_id,
            }.items(),
        ),
        # Stage starts robot_1 at a known world pose and publishes its odom TF.
        # A fixed map->odom transform is deterministic at accelerated sim time
        # and avoids spending CPU on AMCL particle filtering in this profile.
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='robot_1_stage_localization',
            arguments=[
                '--x', '2.3', '--y', '-14.5', '--z', '0.0',
                '--yaw', '1.57079632679', '--pitch', '0.0', '--roll', '0.0',
                '--frame-id', 'map', '--child-frame-id', 'robot_1/odom',
            ],
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
            },
        ),
        ComposableNodeContainer(
            namespace='robot_1',
            name='nav2_container',
            package='rclcpp_components',
            executable='component_container_isolated',
            output='screen',
            parameters=[robot_params],
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
                'RCUTILS_LOGGING_BUFFERED_STREAM': '1',
                'PYTHONPATH': EnvironmentVariable(
                    'PYTHONPATH', default_value=''),
            },
            composable_node_descriptions=components,
        ),
    ])
