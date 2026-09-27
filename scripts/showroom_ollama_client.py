#!/usr/bin/env python3
"""Ollama Chat API client with no ROS or showroom business dependencies."""

import json
import urllib.error
import urllib.request

from showroom_llm_contract import LLMTransportError


def chat_endpoint(endpoint):
    """Accept either an Ollama base URL or the complete chat URL."""
    normalized = endpoint.strip().rstrip('/')
    if not normalized:
        raise LLMTransportError('没有配置 Ollama endpoint')
    if normalized.endswith('/api/chat'):
        return normalized
    return f'{normalized}/api/chat'


class OllamaClient:
    """Call Ollama and return only message.content as the model output."""

    def __init__(self, endpoint, model, timeout_sec=30.0):
        self.endpoint = chat_endpoint(endpoint)
        self.model = model
        self.timeout_sec = float(timeout_sec)

    def post_json(self, payload):
        """POST one JSON document to the configured Ollama endpoint."""
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(
                    request, timeout=self.timeout_sec) as response:
                body = response.read().decode('utf-8')
        except urllib.error.HTTPError as exception:
            detail = exception.read().decode('utf-8', errors='replace')[:500]
            raise LLMTransportError(
                f'Ollama HTTP {exception.code}：{detail}') from exception
        except (urllib.error.URLError, TimeoutError, OSError) as exception:
            raise LLMTransportError(
                f'无法访问 Ollama {self.endpoint}：{exception}') from exception
        try:
            return json.loads(body)
        except json.JSONDecodeError as exception:
            raise LLMTransportError('Ollama 返回的不是 JSON') from exception

    def complete(self, messages):
        """Return message.content and intentionally ignore message.thinking."""
        response = self.post_json({
            'model': self.model,
            'messages': messages,
            'stream': False,
            'format': 'json',
            'think': False,
            'options': {'temperature': 0.1, 'num_predict': 128},
        })
        try:
            content = response['message']['content']
        except (KeyError, TypeError) as exception:
            raise LLMTransportError(
                'Ollama 响应缺少 message.content') from exception
        if not isinstance(content, str) or not content.strip():
            raise LLMTransportError('Ollama message.content 为空')
        return content
