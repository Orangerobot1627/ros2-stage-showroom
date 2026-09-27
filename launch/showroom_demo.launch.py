#!/usr/bin/env python3

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    ros_domain_id = LaunchConfiguration('ros_domain_id')
    coffee_trigger = LaunchConfiguration('coffee_trigger')
    action_policy_file = LaunchConfiguration('action_policy_file')
    override_timeout = LaunchConfiguration('override_timeout_sec')
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
    launch_file = os.path.join(
        get_package_share_directory('demo_stage'),
        'launch',
        'showroom.launch.py',
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'ros_domain_id', default_value='81',
            description='Isolated ROS domain for this showroom simulation.'),
        DeclareLaunchArgument(
            'coffee_trigger', default_value='tunnel_center_south',
            description='Guide waypoint that dispatches the coffee robot.'),
        DeclareLaunchArgument(
            'action_policy_file', default_value='',
            description='Optional task/action policy YAML.'),
        DeclareLaunchArgument(
            'override_timeout_sec', default_value='0.0',
            description='Human override seconds; 0 uses policy default.'),
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
            description='HTTP timeout for one LLM request.'),
        DeclareLaunchArgument(
            'enable_voice', default_value='false',
            description='Start microphone ASR and speaker TTS nodes.'),
        DeclareLaunchArgument(
            'voice_python_path',
            default_value='/home/xxl/ros2_ws/.voice_python'),
        DeclareLaunchArgument(
            'voice_asr_model_path',
            default_value='/home/xxl/ros2_ws/models/faster-whisper-small'),
        DeclareLaunchArgument(
            'voice_tts_model_path',
            default_value=(
                '/home/xxl/ros2_ws/models/piper/'
                'zh_CN-huayan-medium.onnx')),
        DeclareLaunchArgument(
            'voice_input_target', default_value=''),
        DeclareLaunchArgument(
            'voice_output_target', default_value=''),
        DeclareLaunchArgument(
            'voice_rms_threshold', default_value='250.0'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(launch_file),
            launch_arguments={
                'auto_drive': 'true',
                'business_mode': 'true',
                'business_auto_start': 'true',
                'business_start_delay_sec': '3.0',
                'coffee_trigger': coffee_trigger,
                'action_policy_file': action_policy_file,
                'override_timeout_sec': override_timeout,
                'enable_llm': enable_llm,
                'llm_backend': llm_backend,
                'llm_endpoint': llm_endpoint,
                'llm_model': llm_model,
                'llm_request_timeout_sec': llm_request_timeout,
                'enable_voice': enable_voice,
                'voice_python_path': voice_python_path,
                'voice_asr_model_path': voice_asr_model,
                'voice_tts_model_path': voice_tts_model,
                'voice_input_target': voice_input_target,
                'voice_output_target': voice_output_target,
                'voice_rms_threshold': voice_rms_threshold,
                'enable_gui': 'true',
                'one_tf_tree': 'true',
                'software_rendering': '1',
                'ros_domain_id': ros_domain_id,
                'guide_start_delay_sec': '2.0',
                'coffee_start_delay_sec': '0.0',
            }.items(),
        )
    ])
