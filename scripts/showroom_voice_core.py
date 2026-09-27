#!/usr/bin/env python3
"""Provider-independent audio segmentation and voice message helpers."""

from array import array
from collections import deque
import json
import math
import sys
import wave


def pcm_rms(pcm_bytes):
    """Return RMS amplitude for mono signed 16-bit PCM bytes."""
    if not pcm_bytes:
        return 0.0
    samples = array('h')
    samples.frombytes(pcm_bytes[:len(pcm_bytes) // 2 * 2])
    if sys.byteorder != 'little':
        samples.byteswap()
    if not samples:
        return 0.0
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    return math.sqrt(mean_square)


class UtteranceSegmenter:
    """Split a PCM stream into utterances using deterministic energy VAD."""

    def __init__(self, sample_rate=16000, frame_ms=30, rms_threshold=250.0,
                 start_ms=120, end_silence_ms=1800, min_speech_ms=300,
                 max_utterance_sec=20.0, pre_roll_ms=450,
                 release_threshold_ratio=0.60):
        self.sample_rate = int(sample_rate)
        self.frame_ms = int(frame_ms)
        self.frame_bytes = int(
            self.sample_rate * self.frame_ms / 1000) * 2
        self.rms_threshold = float(rms_threshold)
        self.release_threshold = (
            self.rms_threshold * float(release_threshold_ratio))
        self.start_frames = max(1, math.ceil(start_ms / self.frame_ms))
        self.end_frames = max(
            1, math.ceil(end_silence_ms / self.frame_ms))
        self.min_voice_frames = max(
            1, math.ceil(min_speech_ms / self.frame_ms))
        self.max_frames = max(
            1, math.ceil(max_utterance_sec * 1000 / self.frame_ms))
        self.pre_roll = deque(
            maxlen=max(1, math.ceil(pre_roll_ms / self.frame_ms)))
        self.reset()

    def reset(self):
        """Discard the active utterance and VAD counters."""
        self.active = False
        self.frames = []
        self.consecutive_voice = 0
        self.silence_frames = 0
        self.voice_frames = 0
        self.pre_roll.clear()

    def feed(self, frame):
        """Consume one PCM frame and return completed utterance bytes or None."""
        if len(frame) != self.frame_bytes:
            return None
        amplitude = pcm_rms(frame)
        threshold = (
            self.release_threshold if self.active else self.rms_threshold)
        voiced = amplitude >= threshold

        if not self.active:
            self.pre_roll.append(frame)
            self.consecutive_voice = (
                self.consecutive_voice + 1 if voiced else 0)
            if self.consecutive_voice < self.start_frames:
                return None
            self.active = True
            self.frames = list(self.pre_roll)
            self.voice_frames = self.consecutive_voice
            self.silence_frames = 0
            return None

        self.frames.append(frame)
        if voiced:
            self.voice_frames += 1
            self.silence_frames = 0
        else:
            self.silence_frames += 1

        reached_end = (
            self.silence_frames >= self.end_frames
            and self.voice_frames >= self.min_voice_frames)
        reached_limit = len(self.frames) >= self.max_frames
        if not reached_end and not reached_limit:
            return None

        utterance = b''.join(self.frames)
        self.reset()
        return utterance


def write_pcm_wav(path, pcm_bytes, sample_rate=16000):
    """Write mono signed 16-bit PCM bytes to a WAV file."""
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(int(sample_rate))
        stream.writeframes(pcm_bytes)


def assistant_reply(message_data):
    """Extract a non-empty reply from one assistant JSON message."""
    try:
        document = json.loads(message_data)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(document, dict):
        return None
    reply = document.get('reply')
    if not isinstance(reply, str) or not reply.strip():
        return None
    return {
        'request_id': document.get('request_id'),
        'intent': document.get('intent'),
        'reply': reply.strip(),
    }
