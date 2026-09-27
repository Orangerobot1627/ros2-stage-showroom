#!/usr/bin/env python3
"""Validated data contract between language models and showroom business logic."""

import json
import re


COMMAND_INTENTS = {
    'start_tour',
    'request_coffee',
    'pause_tour',
    'resume_tour',
    'cancel_all',
    'reset',
    'robot_action',
    'skip_current',
    'repeat_current',
    'next_task',
    'explain_current',
    'explain_more',
}
NON_COMMAND_INTENTS = {'ask_status', 'chat'}
ALLOWED_INTENTS = COMMAND_INTENTS | NON_COMMAND_INTENTS
INTENT_ALIASES = {
    'cancel_tour': 'cancel_all',
    'stop_tour': 'cancel_all',
    'status': 'ask_status',
    'robot_status': 'ask_status',
}
DEFAULT_REPLIES = {
    'start_tour': '已提交导览任务请求。',
    'request_coffee': '已提交咖啡服务请求。',
    'pause_tour': '已提交暂停导览请求。',
    'resume_tour': '已提交继续导览请求。',
    'cancel_all': '已提交取消全部任务请求。',
    'reset': '已提交系统业务重置请求。',
    'robot_action': '已提交机器人临时动作请求。',
    'skip_current': '好的，已跳过当前展区，继续下一个导览任务。',
    'repeat_current': '好的，我会从头重复当前展区的导览任务。',
    'next_task': '好的，现在进入下一个导览任务。',
    'explain_current': '我来介绍当前展区。',
    'explain_more': '我再详细介绍一下当前展区。',
    'ask_status': '我已经读取当前任务状态，请查看机器人运行信息。',
    'chat': '我目前可以帮助您开始、暂停或继续导览，也可以安排咖啡服务。',
}


class LLMError(RuntimeError):
    """Base error for model transport and output validation."""


class LLMTransportError(LLMError):
    """Raised when a model server cannot return a usable response."""


class LLMOutputError(LLMError):
    """Raised when model output does not match the command contract."""


def extract_json_object(text):
    """Extract the first JSON object from plain text or a Markdown fence."""
    if not isinstance(text, str) or not text.strip():
        raise LLMOutputError('模型返回了空内容')
    cleaned = re.sub(r'^\s*```(?:json)?\s*', '', text.strip(), flags=re.I)
    cleaned = re.sub(r'\s*```\s*$', '', cleaned)
    start = cleaned.find('{')
    if start < 0:
        raise LLMOutputError('模型输出中没有 JSON 对象')
    try:
        document, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exception:
        raise LLMOutputError(
            f'模型输出不是有效 JSON：{exception.msg}') from exception
    if not isinstance(document, dict):
        raise LLMOutputError('模型 JSON 顶层必须是对象')
    return document


def validate_model_result(document):
    """Normalize and validate one model-produced intent document."""
    intent = document.get('intent')
    if not isinstance(intent, str):
        raise LLMOutputError('模型结果缺少字符串 intent')
    intent = INTENT_ALIASES.get(intent.strip().lower(), intent.strip().lower())
    if intent not in ALLOWED_INTENTS:
        raise LLMOutputError(f'模型返回了不允许的 intent：{intent!r}')

    reply = document.get('reply')
    if reply is not None and not isinstance(reply, str):
        raise LLMOutputError('模型结果中的 reply 必须是字符串')
    reply = reply.strip() if isinstance(reply, str) else ''
    model_supplied_reply = bool(reply)

    result = {
        'intent': intent,
        'reply': reply or DEFAULT_REPLIES[intent],
    }
    if intent == 'start_tour':
        coffee = document.get('coffee', True)
        if not isinstance(coffee, bool):
            raise LLMOutputError('start_tour 的 coffee 必须是布尔值')
        result['coffee'] = coffee
    if intent == 'pause_tour' and 'duration_sec' in document:
        duration = document['duration_sec']
        if (not isinstance(duration, (int, float))
                or isinstance(duration, bool) or duration <= 0):
            raise LLMOutputError('pause_tour 的 duration_sec 必须是正数')
        result['duration_sec'] = float(duration)
        if not model_supplied_reply:
            result['reply'] = (
                f'蓝色导览机器人将等待 {float(duration):g} 秒，'
                '随后自动继续原来的导览任务。')
    if intent == 'robot_action':
        robot = document.get('robot')
        action = document.get('action')
        if robot not in ('guide', 'coffee', 'all'):
            raise LLMOutputError(
                'robot_action 的 robot 必须是 guide、coffee 或 all')
        if action not in ('pause', 'resume', 'start_default', 'cancel'):
            raise LLMOutputError('robot_action 包含不允许的 action')
        result.update({'robot': robot, 'action': action})
        if action == 'pause' and 'duration_sec' in document:
            duration = document['duration_sec']
            if (not isinstance(duration, (int, float))
                    or isinstance(duration, bool) or duration <= 0):
                raise LLMOutputError(
                    'robot_action 的 duration_sec 必须是正数')
            result['duration_sec'] = float(duration)
        if not model_supplied_reply:
            robot_name = {
                'guide': '蓝色导览机器人',
                'coffee': '绿色服务机器人',
                'all': '两台机器人',
            }[robot]
            if action == 'pause':
                duration = result.get('duration_sec', 20.0)
                result['reply'] = (
                    f'{robot_name}将等待 {duration:g} 秒，'
                    '随后自动恢复原来的任务。')
            elif action == 'resume':
                result['reply'] = f'{robot_name}现在继续原来的任务。'
            elif action == 'start_default':
                result['reply'] = f'{robot_name}现在开始执行默认任务。'
            else:
                result['reply'] = f'已取消{robot_name}的当前任务。'
    if intent in ('explain_current', 'explain_more'):
        if not model_supplied_reply:
            raise LLMOutputError(f'{intent} 必须包含基于当前任务的 reply')
    return result


def command_from_result(result):
    """Return a task-manager command, or None for conversational intents."""
    if result['intent'] not in COMMAND_INTENTS:
        return None
    command = {'intent': result['intent']}
    if result['intent'] == 'start_tour':
        command['coffee'] = result.get('coffee', True)
    if result['intent'] == 'pause_tour' and 'duration_sec' in result:
        command['duration_sec'] = result['duration_sec']
    if result['intent'] == 'robot_action':
        command.update({
            'robot': result['robot'],
            'action': result['action'],
        })
        if 'duration_sec' in result:
            command['duration_sec'] = result['duration_sec']
    return command
