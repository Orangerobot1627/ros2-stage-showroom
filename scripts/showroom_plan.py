#!/usr/bin/env python3
"""Validated multi-step plans and a small sequential execution state machine."""

from copy import deepcopy


class PlanError(ValueError):
    """Raised when a plan is unsafe, malformed, or cannot be advanced."""


ACTION_ALIASES = {
    'pause_tour': 'pause',
    'resume_tour': 'resume',
    'request_coffee': 'deliver_drink',
    'request_drink': 'deliver_drink',
}
ALLOWED_ACTIONS = {
    'pause',
    'resume',
    'deliver_drink',
    'skip_current',
    'repeat_current',
    'next_task',
    'announce',
    'skip_task',
    'visit_only',
    'bypass_obstacle',
}
ALLOWED_ROBOTS = {'guide', 'coffee', 'all'}
ALLOWED_DRINKS = {'coffee', 'water', 'juice', 'drink'}
ALLOWED_TASKS = {
    'reception', 'technology_history', 'vision_hall', 'robotics_hall',
    'time_tunnel', 'dance_hall', 'lounge',
}


def validate_plan(actions, default_pause_sec=20.0, max_steps=8):
    """Normalize a model plan into a small, closed action vocabulary."""
    if not isinstance(actions, list):
        raise PlanError('plan 必须是 action 数组')
    if not 2 <= len(actions) <= max_steps:
        raise PlanError(f'plan 必须包含 2 到 {max_steps} 个 action')
    normalized = []
    for index, item in enumerate(actions):
        if not isinstance(item, dict):
            raise PlanError(f'plan[{index}] 必须是对象')
        action = str(item.get('action', '')).strip().lower()
        action = ACTION_ALIASES.get(action, action)
        if action not in ALLOWED_ACTIONS:
            raise PlanError(f'plan[{index}] 包含不允许的 action：{action!r}')
        result = {'action': action}
        if action in ('pause', 'resume'):
            robot = str(item.get('robot', 'guide')).strip().lower()
            if robot not in ALLOWED_ROBOTS:
                raise PlanError(
                    f'plan[{index}].robot 必须是 guide、coffee 或 all')
            result['robot'] = robot
            if action == 'pause':
                duration = item.get('duration_sec', default_pause_sec)
                if (not isinstance(duration, (int, float))
                        or isinstance(duration, bool)
                        or not 1.0 <= float(duration) <= 600.0):
                    raise PlanError(
                        f'plan[{index}].duration_sec 必须在 1..600 秒')
                result['duration_sec'] = float(duration)
        elif action == 'deliver_drink':
            drink = str(item.get('drink', 'coffee')).strip().lower()
            if drink not in ALLOWED_DRINKS:
                raise PlanError(f'plan[{index}] 不支持饮料 {drink!r}')
            target = str(item.get('target', 'current_task')).strip()
            if not target or len(target) > 64:
                raise PlanError(f'plan[{index}].target 无效')
            result.update({'drink': drink, 'target': target})
        elif action == 'announce':
            text = str(item.get('text', '')).strip()
            if not text or len(text) > 200:
                raise PlanError(f'plan[{index}].text 必须为 1..200 个字符')
            result['text'] = text
        elif action in ('skip_task', 'visit_only'):
            raw_tasks = item.get('tasks', item.get('task'))
            if isinstance(raw_tasks, str):
                raw_tasks = [raw_tasks]
            if (not isinstance(raw_tasks, list) or not raw_tasks
                    or len(raw_tasks) > len(ALLOWED_TASKS)):
                raise PlanError(
                    f'plan[{index}].tasks 必须是非空场馆数组')
            tasks = list(dict.fromkeys(
                str(value).strip() for value in raw_tasks))
            unknown = [value for value in tasks if value not in ALLOWED_TASKS]
            if unknown:
                raise PlanError(f'plan[{index}] 包含未知场馆：{unknown}')
            result['tasks'] = tasks
        elif action == 'bypass_obstacle':
            robot = str(item.get('robot', 'guide')).strip().lower()
            if robot not in ALLOWED_ROBOTS:
                raise PlanError(
                    f'plan[{index}].robot 必须是 guide、coffee 或 all')
            result['robot'] = robot
        normalized.append(result)
    return normalized


class SequentialPlanExecutor:
    """Track one validated plan while the task manager performs each action."""

    TERMINAL_STATES = {'SUCCEEDED', 'FAILED', 'CANCELLED'}

    def __init__(self):
        self.clear()

    def clear(self):
        self.plan_id = None
        self.state = 'IDLE'
        self.source = None
        self.steps = []
        self.current_index = 0
        self.wait_for = None
        self.error = None

    @property
    def active(self):
        return self.state in {'RUNNING', 'WAITING'}

    @property
    def current(self):
        if not self.active or self.current_index >= len(self.steps):
            return None
        return self.steps[self.current_index]

    def start(self, plan_id, actions, source='visitor'):
        if self.active:
            raise PlanError(f'已有计划正在执行：{self.plan_id}')
        self.plan_id = str(plan_id)
        self.state = 'RUNNING'
        self.source = source
        self.steps = [
            {
                'index': index,
                'action': deepcopy(action),
                'state': 'PENDING',
                'detail': None,
            }
            for index, action in enumerate(actions)
        ]
        self.current_index = 0
        self.wait_for = None
        self.error = None

    def begin_current(self):
        step = self.current
        if step is None:
            raise PlanError('没有可执行的当前 plan step')
        step['state'] = 'RUNNING'
        self.state = 'RUNNING'
        return deepcopy(step['action'])

    def complete_current(self, detail=None):
        step = self.current
        if step is None:
            raise PlanError('没有可完成的当前 plan step')
        step['state'] = 'SUCCEEDED'
        step['detail'] = detail
        self.wait_for = None
        self.current_index += 1
        if self.current_index >= len(self.steps):
            self.state = 'SUCCEEDED'
        else:
            self.state = 'RUNNING'

    def wait_current(self, event_match, detail=None):
        step = self.current
        if step is None:
            raise PlanError('没有可等待的当前 plan step')
        if not isinstance(event_match, dict) or not event_match:
            raise PlanError('异步 plan step 需要事件匹配条件')
        step['state'] = 'WAITING'
        step['detail'] = detail
        self.wait_for = dict(event_match)
        self.state = 'WAITING'

    def observe_event(self, event):
        """Complete the waiting step when all configured fields match."""
        if self.state != 'WAITING' or not isinstance(event, dict):
            return False
        if not all(event.get(key) == value
                   for key, value in self.wait_for.items()):
            return False
        self.complete_current(
            f'event:{event.get("type", "unknown")}')
        return True

    def fail(self, detail):
        if self.current is not None:
            self.current['state'] = 'FAILED'
            self.current['detail'] = str(detail)
        self.state = 'FAILED'
        self.error = str(detail)
        self.wait_for = None

    def cancel(self, detail='cancelled'):
        if self.current is not None:
            self.current['state'] = 'CANCELLED'
            self.current['detail'] = str(detail)
        self.state = 'CANCELLED'
        self.error = str(detail)
        self.wait_for = None

    def snapshot(self):
        return {
            'plan_id': self.plan_id,
            'state': self.state,
            'source': self.source,
            'current_step': (
                self.current_index if self.current_index < len(self.steps)
                else None),
            'step_total': len(self.steps),
            'wait_for': deepcopy(self.wait_for),
            'error': self.error,
            'steps': deepcopy(self.steps),
        }
