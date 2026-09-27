#!/usr/bin/env python3
"""Deterministic tests for multi-step plan validation and execution."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_plan import (  # noqa: E402
    PlanError,
    SequentialPlanExecutor,
    validate_plan,
)


def main():
    actions = validate_plan([
        {'action': 'pause_tour', 'duration_sec': 30},
        {'action': 'request_drink', 'target': 'current_task'},
        {'action': 'announce', 'text': '饮料已经送到。'},
    ])
    assert actions == [
        {'action': 'pause', 'robot': 'guide', 'duration_sec': 30.0},
        {
            'action': 'deliver_drink',
            'drink': 'coffee',
            'target': 'current_task',
        },
        {'action': 'announce', 'text': '饮料已经送到。'},
    ]
    selection = validate_plan([
        {'action': 'visit_only', 'tasks': ['vision_hall', 'dance_hall']},
        {'action': 'bypass_obstacle', 'robot': 'guide'},
    ])
    assert selection[0]['tasks'] == ['vision_hall', 'dance_hall']
    assert selection[1] == {
        'action': 'bypass_obstacle', 'robot': 'guide'}

    executor = SequentialPlanExecutor()
    executor.start('plan-1', actions, source='llm')
    assert executor.begin_current()['action'] == 'pause'
    executor.complete_current('guide paused')
    assert executor.begin_current()['action'] == 'deliver_drink'
    executor.wait_current({
        'type': 'route_completed',
        'robot_id': 'robot_1',
        'mission_id': 'plan-1',
    })
    assert not executor.observe_event({
        'type': 'route_completed', 'robot_id': 'robot_0'})
    assert executor.observe_event({
        'type': 'route_completed',
        'robot_id': 'robot_1',
        'mission_id': 'plan-1',
    })
    assert executor.begin_current()['action'] == 'announce'
    executor.complete_current('announced')
    assert executor.snapshot()['state'] == 'SUCCEEDED'

    for invalid in (
        [],
        [{'action': 'pause'}],
        [{'action': 'fly'}, {'action': 'announce', 'text': 'x'}],
        [{'action': 'pause', 'duration_sec': -1},
         {'action': 'deliver_drink'}],
    ):
        try:
            validate_plan(invalid)
        except PlanError:
            pass
        else:
            raise AssertionError(f'Invalid plan accepted: {invalid!r}')
    print('Multi-step plan validation and sequential execution: OK')


if __name__ == '__main__':
    main()
