#!/usr/bin/env python3

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, RegisterEventHandler, Shutdown
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import (
    EnvironmentVariable,
    LaunchConfiguration,
    PythonExpression,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    package_share = get_package_share_directory('demo_stage')
    world_file = os.path.join(package_share, 'world', 'showroom_final.world')
    route_file = os.path.join(package_share, 'config', 'routes.yaml')

    enable_gui = LaunchConfiguration('enable_gui')
    auto_drive = LaunchConfiguration('auto_drive')
    business_mode = LaunchConfiguration('business_mode')
    business_auto_start = LaunchConfiguration('business_auto_start')
    business_start_delay = LaunchConfiguration('business_start_delay_sec')
    coffee_trigger = LaunchConfiguration('coffee_trigger')
    action_policy_file = LaunchConfiguration('action_policy_file')
    override_timeout = LaunchConfiguration('override_timeout_sec')
    enable_monitor = LaunchConfiguration('enable_monitor')
    enable_llm = LaunchConfiguration('enable_llm')
    llm_backend = LaunchConfiguration('llm_backend')
    llm_endpoint = LaunchConfiguration('llm_endpoint')
    llm_model = LaunchConfiguration('llm_model')
    llm_request_timeout = LaunchConfiguration('llm_request_timeout_sec')
    enable_voice = LaunchConfiguration('enable_voice')
    voice_python_path = LaunchConfiguration('voice_python_path')
    voice_asr_model = LaunchConfiguration('voice_asr_model_path')
    voice_tts_model = LaunchConfiguration('voice_tts_model_path')
    voice_input_target = LaunchConfiguration('voice_input_target')
    voice_output_target = LaunchConfiguration('voice_output_target')
    voice_rms_threshold = LaunchConfiguration('voice_rms_threshold')
    one_tf_tree = LaunchConfiguration('one_tf_tree')
    software_rendering = LaunchConfiguration('software_rendering')
    ros_domain_id = LaunchConfiguration('ros_domain_id')
    guide_start_delay = LaunchConfiguration('guide_start_delay_sec')
    coffee_start_delay = LaunchConfiguration('coffee_start_delay_sec')
    navigation_backend = LaunchConfiguration('navigation_backend')

    stage_node = Node(
        package='stage_ros2',
        executable='stage_ros2',
        name='stage',
        output='screen',
        additional_env={
            'LIBGL_ALWAYS_SOFTWARE': software_rendering,
            'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
            'ROS_DOMAIN_ID': ros_domain_id,
        },
        parameters=[{
            'world_file': world_file,
            'enable_gui': enable_gui,
            'use_stamped_velocity': False,
            'use_ackermann': False,
            'enforce_prefixes': True,
            'one_tf_tree': one_tf_tree,
            'use_static_transformations': True,
            'base_watchdog_timeout': 0.8,
            'publish_ground_truth': True,
        }],
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'enable_gui', default_value='true',
            description='Show the Stage GUI.'),
        DeclareLaunchArgument(
            'auto_drive', default_value='false',
            description='Start the reference waypoint followers.'),
        DeclareLaunchArgument(
            'business_mode', default_value='false',
            description='Coordinate both route followers with the task manager.'),
        DeclareLaunchArgument(
            'business_auto_start', default_value='true',
            description='Automatically begin the guide scenario.'),
        DeclareLaunchArgument(
            'business_start_delay_sec', default_value='3.0',
            description='Simulation-time delay before starting the scenario.'),
        DeclareLaunchArgument(
            'coffee_trigger', default_value='tunnel_center_south',
            description=(
                'Guide waypoint label that dispatches the coffee robot in '
                'business mode.')),
        DeclareLaunchArgument(
            'action_policy_file', default_value='',
            description=(
                'Optional task/action policy YAML; empty uses the package '
                'default.')),
        DeclareLaunchArgument(
            'override_timeout_sec', default_value='0.0',
            description=(
                'Human override duration in wall-clock seconds; 0 uses '
                'action_policy.yaml.')),
        DeclareLaunchArgument(
            'enable_monitor', default_value='true',
            description='Publish aggregated state on /showroom/monitor.'),
        DeclareLaunchArgument(
            'enable_llm', default_value='false',
            description='Start the natural-language LLM bridge.'),
        DeclareLaunchArgument(
            'llm_backend', default_value='ollama',
            description='LLM adapter: mock, openai_compatible, or ollama.'),
        DeclareLaunchArgument(
            'llm_endpoint', default_value='http://192.168.23.1:11434',
            description='Ollama base URL or full model chat endpoint.'),
        DeclareLaunchArgument(
            'llm_model', default_value='qwen3.5:4b',
            description='Model identifier sent to the LLM server.'),
        DeclareLaunchArgument(
            'llm_request_timeout_sec', default_value='30.0',
            description='HTTP timeout for one LLM inference request.'),
        DeclareLaunchArgument(
            'enable_voice', default_value='false',
            description='Start microphone ASR and speaker TTS nodes.'),
        DeclareLaunchArgument(
            'voice_python_path',
            default_value='/home/xxl/ros2_ws/.voice_python',
            description='Private Python dependency directory for ASR/TTS.'),
        DeclareLaunchArgument(
            'voice_asr_model_path',
            default_value='/home/xxl/ros2_ws/models/faster-whisper-small',
            description='Local faster-whisper model directory.'),
        DeclareLaunchArgument(
            'voice_tts_model_path',
            default_value=(
                '/home/xxl/ros2_ws/models/piper/'
                'zh_CN-huayan-medium.onnx'),
            description='Local Piper ONNX voice model.'),
        DeclareLaunchArgument(
            'voice_input_target', default_value='',
            description='Optional PipeWire microphone node name or serial.'),
        DeclareLaunchArgument(
            'voice_output_target', default_value='',
            description='Optional PipeWire speaker node name or serial.'),
        DeclareLaunchArgument(
            'voice_rms_threshold', default_value='250.0',
            description='Energy threshold used to start speech capture.'),
        DeclareLaunchArgument(
            'one_tf_tree', default_value='true',
            description='Publish both robots in one prefixed /tf tree.'),
        DeclareLaunchArgument(
            'software_rendering', default_value='1',
            description='Use Mesa software rendering; recommended in VMware.'),
        DeclareLaunchArgument(
            'ros_domain_id', default_value='81',
            description='Isolated ROS domain for this showroom simulation.'),
        DeclareLaunchArgument(
            'guide_start_delay_sec', default_value='2.0',
            description='Simulation-time delay before robot_0 starts.'),
        DeclareLaunchArgument(
            'coffee_start_delay_sec', default_value='400.0',
            description=(
                'Autonomous-mode delay before robot_1 starts; task-manager '
                'start commands bypass this delay.')),
        DeclareLaunchArgument(
            'navigation_backend', default_value='stage_graph',
            description=(
                'Semantic navigation backend: stage_graph or nav2. Nav2 '
                'requires a running namespaced Nav2 stack.')),

        stage_node,
        RegisterEventHandler(
            OnProcessExit(
                target_action=stage_node,
                on_exit=[Shutdown(reason='Stage process exited')],
            )
        ),

        Node(
            package='demo_stage',
            executable='showroom_task_manager.py',
            name='showroom_task_manager',
            output='screen',
            condition=IfCondition(business_mode),
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
            },
            parameters=[{
                'use_sim_time': True,
                'auto_start': business_auto_start,
                'auto_start_delay_sec': business_start_delay,
                'coffee_trigger': coffee_trigger,
                'action_policy_file': ParameterValue(
                    action_policy_file, value_type=str),
                'override_timeout_sec': override_timeout,
            }],
        ),

        Node(
            package='demo_stage',
            executable='showroom_monitor.py',
            name='showroom_monitor',
            output='screen',
            condition=IfCondition(enable_monitor),
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
            },
            parameters=[{'use_sim_time': True}],
        ),

        Node(
            package='demo_stage',
            executable='showroom_navigation_gateway.py',
            name='showroom_navigation_gateway',
            output='screen',
            condition=IfCondition(business_mode),
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
            },
            parameters=[{
                'use_sim_time': True,
                'backend': navigation_backend,
            }],
        ),

        Node(
            package='demo_stage',
            executable='showroom_nav2_adapter.py',
            namespace='robot_1',
            name='showroom_nav2_adapter',
            output='screen',
            condition=IfCondition(PythonExpression([
                "'", business_mode, "'.lower() == 'true' and '",
                navigation_backend, "' == 'nav2'",
            ])),
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
            },
            parameters=[{
                'use_sim_time': True,
                'robot_id': 'robot_1',
                'action_name': 'navigate_through_poses',
                'frame_id': 'map',
            }],
        ),

        Node(
            package='demo_stage',
            executable='showroom_llm_bridge.py',
            name='showroom_llm_bridge',
            output='screen',
            condition=IfCondition(enable_llm),
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
            },
            parameters=[{
                'backend': llm_backend,
                'endpoint': llm_endpoint,
                'model': llm_model,
                'request_timeout_sec': llm_request_timeout,
            }],
        ),

        Node(
            package='demo_stage',
            executable='showroom_asr.py',
            name='showroom_asr',
            output='screen',
            condition=IfCondition(enable_voice),
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
                'PYTHONPATH': [
                    voice_python_path, ':',
                    EnvironmentVariable('PYTHONPATH', default_value=''),
                ],
            },
            parameters=[{
                'model_path': voice_asr_model,
                'input_target': ParameterValue(
                    voice_input_target, value_type=str),
                'rms_threshold': voice_rms_threshold,
            }],
        ),

        Node(
            package='demo_stage',
            executable='showroom_tts.py',
            name='showroom_tts',
            output='screen',
            condition=IfCondition(enable_voice),
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
                'PYTHONPATH': [
                    voice_python_path, ':',
                    EnvironmentVariable('PYTHONPATH', default_value=''),
                ],
            },
            parameters=[{
                'model_path': voice_tts_model,
                'output_target': ParameterValue(
                    voice_output_target, value_type=str),
            }],
        ),

        Node(
            package='demo_stage',
            executable='waypoint_follower.py',
            namespace='robot_0',
            name='guide_route_follower',
            output='screen',
            condition=IfCondition(auto_drive),
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
            },
            parameters=[{
                'use_sim_time': True,
                'route_file': route_file,
                'route_name': 'guide_full_route',
                'robot_id': 'robot_0',
                'wait_for_start_command': business_mode,
                'pose_topic': 'ground_truth',
                'start_delay_sec': guide_start_delay,
                'max_linear_speed': 0.65,
                'max_angular_speed': 1.2,
                'obstacle_stop_distance': 0.60,
                'avoidance_trigger_distance': 0.64,
            }],
        ),

        Node(
            package='demo_stage',
            executable='waypoint_follower.py',
            namespace='robot_1',
            name='coffee_route_follower',
            output='screen',
            condition=IfCondition(PythonExpression([
                "'", auto_drive, "'.lower() == 'true' and '",
                navigation_backend, "' == 'stage_graph'",
            ])),
            additional_env={
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST',
                'ROS_DOMAIN_ID': ros_domain_id,
            },
            parameters=[{
                'use_sim_time': True,
                'route_file': route_file,
                'route_name': 'coffee_delivery_route',
                'robot_id': 'robot_1',
                'wait_for_start_command': business_mode,
                'pose_topic': 'ground_truth',
                'start_delay_sec': coffee_start_delay,
                'max_linear_speed': 0.55,
                'max_angular_speed': 1.1,
                'obstacle_stop_distance': 0.65,
                'avoidance_trigger_distance': 0.70,
            }],
        ),
    ])
