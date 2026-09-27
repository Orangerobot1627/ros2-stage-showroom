#!/usr/bin/env python3
"""ROS 2 bridge between visitor text, a local LLM, and showroom commands."""

import json
from pathlib import Path
import queue
import threading
import time

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from showroom_llm_contract import (
    command_from_result,
    extract_json_object,
    LLMError,
    validate_model_result,
)
from showroom_llm_core import create_backend
from showroom_llm_prompt import build_messages
from std_msgs.msg import String
import yaml


class ShowroomLLMBridge(Node):
    """Convert natural language into validated high-level business intents."""

    def __init__(self):
        super().__init__('showroom_llm_bridge')
        self.declare_parameter('backend', 'ollama')
        self.declare_parameter(
            'endpoint', 'http://192.168.23.1:11434')
        self.declare_parameter('model', 'qwen3.5:4b')
        self.declare_parameter('request_timeout_sec', 30.0)
        self.declare_parameter('api_key_env', 'SHOWROOM_LLM_API_KEY')
        self.declare_parameter('user_topic', '/showroom/user_text')
        self.declare_parameter('assistant_topic', '/showroom/assistant_text')
        self.declare_parameter('command_topic', '/showroom/command')
        self.declare_parameter('status_topic', '/showroom/llm_status')
        self.declare_parameter('knowledge_file', '')
        self.declare_parameter('max_pending_requests', 4)

        self.backend_name = str(self.get_parameter('backend').value)
        self.endpoint = str(self.get_parameter('endpoint').value)
        self.model_name = str(self.get_parameter('model').value)
        timeout = float(self.get_parameter('request_timeout_sec').value)
        api_key_env = str(self.get_parameter('api_key_env').value)
        self.backend = create_backend(
            self.backend_name,
            endpoint=self.endpoint,
            model=self.model_name,
            timeout_sec=timeout,
            api_key_env=api_key_env,
        )
        self.knowledge = self.load_knowledge()

        transient_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.command_publisher = self.create_publisher(
            String, self.get_parameter('command_topic').value, 10)
        self.assistant_publisher = self.create_publisher(
            String, self.get_parameter('assistant_topic').value,
            transient_qos)
        self.llm_status_publisher = self.create_publisher(
            String, self.get_parameter('status_topic').value,
            transient_qos)
        self.create_subscription(
            String, self.get_parameter('user_topic').value,
            self.user_callback, 10)
        self.create_subscription(
            String, '/showroom/status', self.business_status_callback,
            transient_qos)
        self.create_subscription(
            String, '/showroom/monitor', self.monitor_callback,
            transient_qos)
        self.create_subscription(
            String, '/showroom/response', self.command_response_callback, 10)

        max_pending = int(self.get_parameter('max_pending_requests').value)
        self.pending = queue.Queue(maxsize=max(1, max_pending))
        self.completed = queue.Queue()
        self.state_lock = threading.Lock()
        self.business_status = {}
        self.monitor = {}
        self.last_command_response = {}
        self.request_sequence = 0
        self.busy = False
        self.last_error = None
        self.stopping = threading.Event()
        self.worker = threading.Thread(
            target=self.worker_loop,
            name='showroom-llm-worker',
            daemon=True,
        )
        self.worker.start()
        self.create_timer(0.05, self.publish_completed)
        self.create_timer(1.0, self.publish_bridge_status)
        self.publish_bridge_status()
        self.get_logger().info(
            f'LLM bridge ready: backend={self.backend_name}, '
            f'model={self.model_name!r}, user_topic='
            f'{self.get_parameter("user_topic").value!r}')

    def load_knowledge(self):
        configured = str(self.get_parameter('knowledge_file').value)
        if configured:
            path = Path(configured).expanduser()
        else:
            path = Path(get_package_share_directory('demo_stage')) \
                / 'config' / 'landmarks.yaml'
        try:
            document = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        except (OSError, yaml.YAMLError) as exception:
            self.get_logger().warning(
                f'Cannot read knowledge file {path}: {exception}')
            return ''
        zones = document.get('zones') or {}
        zone_names = ', '.join(zones.keys())
        return f'展馆区域：{zone_names}。地图坐标系为 world。'

    @staticmethod
    def parse_json_message(message):
        try:
            document = json.loads(message.data)
        except (json.JSONDecodeError, TypeError):
            return {}
        return document if isinstance(document, dict) else {}

    def business_status_callback(self, message):
        document = self.parse_json_message(message)
        with self.state_lock:
            self.business_status = document

    def monitor_callback(self, message):
        document = self.parse_json_message(message)
        with self.state_lock:
            self.monitor = document

    def command_response_callback(self, message):
        document = self.parse_json_message(message)
        with self.state_lock:
            self.last_command_response = document

    def user_callback(self, message):
        user_text = message.data.strip()
        if not user_text:
            self.publish_error(None, '游客输入为空')
            return
        self.request_sequence += 1
        request = {
            'request_id': self.request_sequence,
            'user_text': user_text,
            'received_at': time.time(),
        }
        try:
            self.pending.put_nowait(request)
            self.get_logger().info(
                f'Queued visitor request #{self.request_sequence}: '
                f'{user_text[:80]}')
        except queue.Full:
            self.publish_error(
                self.request_sequence,
                'LLM 请求队列已满，请稍后重试。')

    def worker_loop(self):
        while not self.stopping.is_set():
            try:
                request = self.pending.get(timeout=0.1)
            except queue.Empty:
                continue
            self.busy = True
            try:
                with self.state_lock:
                    business = dict(self.business_status)
                    monitor = dict(self.monitor)
                messages = build_messages(
                    request['user_text'],
                    business=business,
                    monitor=monitor,
                    knowledge=self.knowledge,
                )
                raw_output = self.backend.complete(messages)
                result = validate_model_result(extract_json_object(raw_output))
                self.completed.put({
                    'request_id': request['request_id'],
                    'user_text': request['user_text'],
                    'result': result,
                    'raw_output': raw_output,
                })
                self.last_error = None
            except (LLMError, ValueError, TypeError) as exception:
                self.last_error = str(exception)
                self.completed.put({
                    'request_id': request['request_id'],
                    'user_text': request['user_text'],
                    'error': str(exception),
                })
            except Exception as exception:  # Keep the worker alive.
                self.last_error = f'未预期的 LLM 错误：{exception}'
                self.completed.put({
                    'request_id': request['request_id'],
                    'user_text': request['user_text'],
                    'error': self.last_error,
                })
            finally:
                self.busy = False
                self.pending.task_done()

    def publish_completed(self):
        while True:
            try:
                completed = self.completed.get_nowait()
            except queue.Empty:
                return
            if 'error' in completed:
                self.publish_error(
                    completed['request_id'], completed['error'])
                continue

            result = completed['result']
            command = command_from_result(result)
            dispatched = command is not None
            if command is not None:
                command_message = String()
                command_message.data = json.dumps(
                    command, ensure_ascii=False, separators=(',', ':'))
                self.command_publisher.publish(command_message)

            response = {
                'type': 'llm_assistant_response',
                'request_id': completed['request_id'],
                'backend': self.backend_name,
                'model': self.model_name,
                'intent': result['intent'],
                'reply': result['reply'],
                'command_dispatched': dispatched,
                'command': command,
            }
            message = String()
            message.data = json.dumps(
                response, ensure_ascii=False, separators=(',', ':'))
            self.assistant_publisher.publish(message)
            self.get_logger().info(
                f'Request #{completed["request_id"]}: '
                f'intent={result["intent"]}, dispatched={dispatched}')

    def publish_error(self, request_id, detail):
        response = {
            'type': 'llm_assistant_response',
            'request_id': request_id,
            'backend': self.backend_name,
            'model': self.model_name,
            'intent': 'error',
            'reply': f'语言模型暂时无法处理请求：{detail}',
            'command_dispatched': False,
            'command': None,
        }
        message = String()
        message.data = json.dumps(
            response, ensure_ascii=False, separators=(',', ':'))
        self.assistant_publisher.publish(message)
        self.get_logger().error(str(detail))

    def publish_bridge_status(self):
        document = {
            'type': 'llm_bridge_status',
            'backend': self.backend_name,
            'model': self.model_name,
            'endpoint': self.endpoint,
            'busy': self.busy,
            'pending_requests': self.pending.qsize(),
            'last_error': self.last_error,
        }
        message = String()
        message.data = json.dumps(
            document, ensure_ascii=False, separators=(',', ':'))
        self.llm_status_publisher.publish(message)

    def destroy_node(self):
        self.stopping.set()
        self.worker.join(timeout=0.5)
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ShowroomLLMBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except (Exception, KeyboardInterrupt):
            pass


if __name__ == '__main__':
    main()
