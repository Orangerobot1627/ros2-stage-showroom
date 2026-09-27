#!/usr/bin/env python3
"""Deterministic tests for voice segmentation and assistant reply parsing."""

from array import array
import json
from pathlib import Path
import sys
import tempfile
import wave


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_voice_core import (  # noqa: E402
    assistant_reply,
    pcm_rms,
    UtteranceSegmenter,
    write_pcm_wav,
)


def pcm_frame(value, samples):
    """Build one constant signed 16-bit PCM frame."""
    return array('h', [value] * samples).tobytes()


def main():
    segmenter = UtteranceSegmenter(
        sample_rate=1000,
        frame_ms=20,
        rms_threshold=100,
        start_ms=40,
        end_silence_ms=60,
        min_speech_ms=60,
        max_utterance_sec=2,
        pre_roll_ms=40,
    )
    samples = segmenter.frame_bytes // 2
    silence = pcm_frame(0, samples)
    voice = pcm_frame(1000, samples)
    assert pcm_rms(silence) == 0.0
    assert int(pcm_rms(voice)) == 1000

    output = None
    for frame in [silence, voice, voice, voice, silence, silence, silence]:
        output = segmenter.feed(frame) or output
    assert output is not None
    assert len(output) >= len(voice) * 3

    response = assistant_reply(json.dumps({
        'request_id': 3,
        'intent': 'pause_tour',
        'reply': ' 已提交暂停请求。 ',
    }, ensure_ascii=False))
    assert response == {
        'request_id': 3,
        'intent': 'pause_tour',
        'reply': '已提交暂停请求。',
    }
    assert assistant_reply('not-json') is None
    assert assistant_reply('{"reply":""}') is None

    with tempfile.NamedTemporaryFile(suffix='.wav') as temporary:
        write_pcm_wav(temporary.name, voice * 3, sample_rate=1000)
        with wave.open(temporary.name, 'rb') as stream:
            assert stream.getnchannels() == 1
            assert stream.getsampwidth() == 2
            assert stream.getframerate() == 1000
            assert stream.getnframes() == samples * 3

    print('Voice VAD, WAV, and assistant reply scenarios: OK')


if __name__ == '__main__':
    main()
