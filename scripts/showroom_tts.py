#!/usr/bin/env python3
"""Synthesize showroom assistant replies and play them through PipeWire."""

import json
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import wave

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from showroom_voice_core import assistant_reply
from std_msgs.msg import Bool, String


class ShowroomTTS(Node):
    """Piper text-to-speech and PipeWire playback ROS adapter."""

    def __init__(self):
        super().__init__('showroom_tts')
        self.declare_parameter(
            'model_path',
            '/home/xxl/ros2_ws/models/piper/zh_CN-huayan-medium.onnx')
        self.declare_parameter('output_target', '')
        self.declare_parameter(
            'assistant_topic', '/showroom/assistant_text')
        self.declare_parameter('say_topic', '/showroom/voice/say')
        self.declare_parameter(
            'speaking_topic', '/showroom/voice/speaking')
        self.declare_parameter('status_topic', '/showroom/voice/tts_status')

        transient = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.speaking_publisher = self.create_publisher(
            Bool, self.get_parameter('speaking_topic').value, transient)
        self.status_publisher = self.create_publisher(
            String, self.get_parameter('status_topic').value, transient)
        self.create_subscription(
            String, self.get_parameter('assistant_topic').value,
            self.assistant_callback, 10)
        self.create_subscription(
            String, self.get_parameter('say_topic').value,
            self.say_callback, 10)

        self.requests = queue.Queue(maxsize=4)
        self.stopping = threading.Event()
        self.last_request_id = None
        self.worker = threading.Thread(
            target=self.worker_loop, name='showroom-tts-worker', daemon=True)
        self.publish_speaking(False)
        self.worker.start()

    def publish_status(self, state, detail='', **extra):
        """Publish an observable TTS state document."""
        document = {'type': 'tts_status', 'state': state, 'detail': detail}
        document.update(extra)
        message = String()
        message.data = json.dumps(
            document, ensure_ascii=False, separators=(',', ':'))
        self.status_publisher.publish(message)

    def publish_speaking(self, active):
        """Notify ASR that robot speech is or is not playing."""
        message = Bool()
        message.data = bool(active)
        self.speaking_publisher.publish(message)

    def enqueue(self, text, request_id=None, intent=None):
        """Queue one non-empty sentence without blocking a ROS callback."""
        text = text.strip()
        if not text:
            return
        try:
            self.requests.put_nowait({
                'text': text,
                'request_id': request_id,
                'intent': intent,
            })
        except queue.Full:
            self.publish_status('DROPPED', 'TTS 队列已满')

    def assistant_callback(self, message):
        """Speak the validated reply portion of an assistant response."""
        response = assistant_reply(message.data)
        if response is None:
            return
        request_id = response['request_id']
        if request_id is not None and request_id == self.last_request_id:
            return
        self.last_request_id = request_id
        self.enqueue(
            response['reply'], request_id=request_id,
            intent=response['intent'])

    def say_callback(self, message):
        """Speak text sent directly to the diagnostic say topic."""
        self.enqueue(message.data)

    def playback_command(self, wav_path):
        """Build a PipeWire playback command for one WAV file."""
        command = ['pw-play']
        target = str(self.get_parameter('output_target').value).strip()
        if target:
            command.extend(['--target', target])
        command.append(str(wav_path))
        return command

    def worker_loop(self):
        """Load Piper once, then synthesize and play queued replies."""
        self.publish_status('LOADING_MODEL', '正在加载 Piper 中文音色')
        try:
            from piper import PiperVoice
            voice = PiperVoice.load(
                str(self.get_parameter('model_path').value))
        except Exception as exception:
            self.publish_status('ERROR', f'Piper 加载失败：{exception}')
            return
        self.publish_status('READY', 'Piper 已就绪')

        while not self.stopping.is_set():
            try:
                request = self.requests.get(timeout=0.1)
            except queue.Empty:
                continue
            wav_path = None
            started = time.monotonic()
            self.publish_speaking(True)
            try:
                with tempfile.NamedTemporaryFile(
                        prefix='showroom-tts-', suffix='.wav',
                        delete=False) as temporary:
                    wav_path = Path(temporary.name)
                with wave.open(str(wav_path), 'wb') as wav_file:
                    voice.synthesize_wav(request['text'], wav_file)
                self.publish_status(
                    'PLAYING', '正在播放机器人回复',
                    text=request['text'], intent=request['intent'])
                completed = subprocess.run(
                    self.playback_command(wav_path),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=30.0,
                    check=False,
                )
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip())
                self.publish_status(
                    'READY', '播放完成',
                    latency_sec=round(time.monotonic() - started, 3))
            except Exception as exception:
                self.publish_status('ERROR', f'语音合成或播放失败：{exception}')
            finally:
                self.publish_speaking(False)
                if wav_path is not None:
                    try:
                        wav_path.unlink()
                    except OSError:
                        pass
                self.requests.task_done()

    def destroy_node(self):
        """Stop the TTS worker before destroying the ROS node."""
        self.stopping.set()
        self.worker.join(timeout=1.0)
        return super().destroy_node()


def main(args=None):
    """Run the showroom TTS node."""
    rclpy.init(args=args)
    node = ShowroomTTS()
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
