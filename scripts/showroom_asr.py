#!/usr/bin/env python3
"""Capture microphone speech, transcribe it, and publish showroom user text."""

import json
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from showroom_voice_core import UtteranceSegmenter, write_pcm_wav
from std_msgs.msg import Bool, String


class ShowroomASR(Node):
    """PipeWire microphone and faster-whisper ROS adapter."""

    def __init__(self):
        super().__init__('showroom_asr')
        self.declare_parameter(
            'model_path', '/home/xxl/ros2_ws/models/faster-whisper-small')
        self.declare_parameter('device', 'cpu')
        self.declare_parameter('compute_type', 'int8')
        self.declare_parameter('cpu_threads', 4)
        self.declare_parameter('language', 'zh')
        self.declare_parameter(
            'initial_prompt',
            '未来科技展馆。游客可以说：我想在智能机器人展厅多待一会儿，'
            '先别往前走；请绿色服务机器人送一杯咖啡过来；'
            '跳过科技舞蹈展厅；直接去休息服务区。常用场馆：'
            '科技发展历史展区、计算机视觉展厅、智能机器人展厅、'
            '时空科技隧道、科技舞蹈展厅、智能休息服务区。')
        self.declare_parameter(
            'hotwords',
            '未来科技展馆 开始导览 暂停导览 继续参观 跳过展厅 '
            '智能机器人展厅 多待一会儿 先别往前走 '
            '绿色服务机器人 送一杯咖啡 科技发展历史 '
            '计算机视觉 时空科技隧道 科技舞蹈展厅 '
            '直接去休息服务区 饮料 Nav2')
        self.declare_parameter('beam_size', 3)
        self.declare_parameter('input_target', '')
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('frame_ms', 30)
        self.declare_parameter('rms_threshold', 250.0)
        self.declare_parameter('start_ms', 120)
        self.declare_parameter('end_silence_ms', 1800)
        self.declare_parameter('min_speech_ms', 300)
        self.declare_parameter('max_utterance_sec', 20.0)
        self.declare_parameter('pre_roll_ms', 450)
        self.declare_parameter('release_threshold_ratio', 0.60)
        self.declare_parameter('queue_capacity', 4)
        self.declare_parameter('user_topic', '/showroom/user_text')
        self.declare_parameter(
            'transcript_topic', '/showroom/voice/transcript')
        self.declare_parameter('status_topic', '/showroom/voice/asr_status')
        self.declare_parameter(
            'speaking_topic', '/showroom/voice/speaking')

        transient = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.user_publisher = self.create_publisher(
            String, self.get_parameter('user_topic').value, 10)
        self.transcript_publisher = self.create_publisher(
            String, self.get_parameter('transcript_topic').value, transient)
        self.status_publisher = self.create_publisher(
            String, self.get_parameter('status_topic').value, transient)
        self.create_subscription(
            Bool, self.get_parameter('speaking_topic').value,
            self.speaking_callback, transient)

        self.sample_rate = int(self.get_parameter('sample_rate').value)
        self.segmenter = UtteranceSegmenter(
            sample_rate=self.sample_rate,
            frame_ms=int(self.get_parameter('frame_ms').value),
            rms_threshold=float(self.get_parameter('rms_threshold').value),
            start_ms=int(self.get_parameter('start_ms').value),
            end_silence_ms=int(
                self.get_parameter('end_silence_ms').value),
            min_speech_ms=int(self.get_parameter('min_speech_ms').value),
            max_utterance_sec=float(
                self.get_parameter('max_utterance_sec').value),
            pre_roll_ms=int(self.get_parameter('pre_roll_ms').value),
            release_threshold_ratio=float(
                self.get_parameter('release_threshold_ratio').value),
        )
        self.utterances = queue.Queue(maxsize=int(
            self.get_parameter('queue_capacity').value))
        self.stopping = threading.Event()
        self.tts_speaking = threading.Event()
        self.capture_process = None
        self.capture_thread = threading.Thread(
            target=self.capture_loop, name='showroom-microphone', daemon=True)
        self.asr_thread = threading.Thread(
            target=self.asr_loop, name='showroom-asr-worker', daemon=True)
        self.capture_thread.start()
        self.asr_thread.start()

    def publish_status(self, state, detail='', **extra):
        """Publish an observable ASR state document."""
        document = {'type': 'asr_status', 'state': state, 'detail': detail}
        document.update(extra)
        message = String()
        message.data = json.dumps(
            document, ensure_ascii=False, separators=(',', ':'))
        self.status_publisher.publish(message)

    def speaking_callback(self, message):
        """Pause recognition while synthesized speech is playing."""
        if message.data:
            self.tts_speaking.set()
            self.segmenter.reset()
        else:
            self.tts_speaking.clear()

    def capture_command(self):
        """Build the PipeWire raw PCM recording command."""
        command = [
            'pw-record',
            '--rate', str(self.sample_rate),
            '--channels', '1',
            '--format', 's16',
        ]
        target = str(self.get_parameter('input_target').value).strip()
        if target:
            command.extend(['--target', target])
        command.append('-')
        return command

    def capture_loop(self):
        """Read raw microphone PCM and form utterance work items."""
        try:
            self.capture_process = subprocess.Popen(
                self.capture_command(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exception:
            self.publish_status('ERROR', f'无法启动 pw-record：{exception}')
            return

        self.publish_status('LISTENING', '麦克风采集已启动')
        stream = self.capture_process.stdout
        while not self.stopping.is_set() and stream is not None:
            frame = stream.read(self.segmenter.frame_bytes)
            if len(frame) != self.segmenter.frame_bytes:
                break
            if self.tts_speaking.is_set():
                self.segmenter.reset()
                continue
            utterance = self.segmenter.feed(frame)
            if utterance is None:
                continue
            try:
                self.utterances.put_nowait(utterance)
                self.publish_status(
                    'TRANSCRIBING', '检测到一句语音',
                    audio_duration_sec=round(
                        len(utterance) / 2 / self.sample_rate, 3),
                )
            except queue.Full:
                self.publish_status('DROPPED', 'ASR 队列已满')

        if not self.stopping.is_set():
            self.publish_status('ERROR', 'PipeWire 录音流已结束')

    def asr_loop(self):
        """Load faster-whisper once and transcribe queued utterances."""
        self.publish_status('LOADING_MODEL', '正在加载 Whisper 模型')
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(
                str(self.get_parameter('model_path').value),
                device=str(self.get_parameter('device').value),
                compute_type=str(self.get_parameter('compute_type').value),
                cpu_threads=int(self.get_parameter('cpu_threads').value),
            )
        except Exception as exception:
            self.publish_status('ERROR', f'Whisper 加载失败：{exception}')
            return
        self.publish_status('LISTENING', 'Whisper 已就绪')

        while not self.stopping.is_set():
            try:
                utterance = self.utterances.get(timeout=0.1)
            except queue.Empty:
                continue
            wav_path = None
            started = time.monotonic()
            try:
                with tempfile.NamedTemporaryFile(
                        prefix='showroom-asr-', suffix='.wav',
                        delete=False) as temporary:
                    wav_path = Path(temporary.name)
                write_pcm_wav(wav_path, utterance, self.sample_rate)
                segments, _ = model.transcribe(
                    str(wav_path),
                    language=str(self.get_parameter('language').value),
                    beam_size=int(self.get_parameter('beam_size').value),
                    condition_on_previous_text=False,
                    initial_prompt=str(
                        self.get_parameter('initial_prompt').value),
                    hotwords=str(self.get_parameter('hotwords').value),
                    # The streaming segmenter has already produced one
                    # complete utterance. A second VAD pass can remove quiet
                    # Chinese syllables at the start or end of the command.
                    vad_filter=False,
                )
                text = ''.join(segment.text for segment in segments).strip()
                if text:
                    transcript = String()
                    transcript.data = text
                    self.transcript_publisher.publish(transcript)
                    self.user_publisher.publish(transcript)
                    self.get_logger().info(f'ASR: {text}')
                    self.publish_status(
                        'LISTENING', '识别完成', transcript=text,
                        latency_sec=round(time.monotonic() - started, 3),
                    )
                else:
                    self.publish_status('LISTENING', '未识别到有效文字')
            except Exception as exception:
                self.publish_status('ERROR', f'语音识别失败：{exception}')
            finally:
                if wav_path is not None:
                    try:
                        wav_path.unlink()
                    except OSError:
                        pass
                self.utterances.task_done()

    def destroy_node(self):
        """Stop audio and inference workers before destroying the ROS node."""
        self.stopping.set()
        if self.capture_process is not None:
            self.capture_process.terminate()
        self.capture_thread.join(timeout=1.0)
        self.asr_thread.join(timeout=1.0)
        return super().destroy_node()


def main(args=None):
    """Run the showroom ASR node."""
    rclpy.init(args=args)
    node = ShowroomASR()
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
