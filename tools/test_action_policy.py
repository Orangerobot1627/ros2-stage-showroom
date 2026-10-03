#!/usr/bin/env python3
"""Deterministic tests for action policy and override leases."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_action_policy import (  # noqa: E402
    ActionPolicy,
    ActionPolicyError,
    OverrideLeaseBook,
    TemporaryMissionLease,
)


def main():
    policy = ActionPolicy.from_file(ROOT / 'config' / 'action_policy.yaml')
    assert policy.default_duration == 20.0
    assert policy.resolve_robots('guide') == ['robot_0']
    assert policy.resolve_robots('绿色机器人') == ['robot_1']
    assert policy.resolve_robots('all') == ['robot_0', 'robot_1']
    assert policy.validate_action('pause', 'all') == 'pause'
    assert policy.validate_action(
        'bypass_obstacle', 'coffee') == 'bypass_obstacle'
    assert policy.duration() == 20.0
    assert policy.duration(1.0) == 2.0
    assert policy.duration(999.0) == 120.0
    assert policy.navigation_timeout() == 300.0
    assert policy.navigation_timeout(999.0) == 600.0
    assert policy.dwell_duration(999.0) == 120.0
    try:
        policy.validate_action('start_default', 'all')
    except ActionPolicyError:
        pass
    else:
        raise AssertionError('all/start_default must be rejected')

    leases = OverrideLeaseBook()
    lease = leases.begin(
        'robot_0', 'pause', now=10.0, duration=20.0,
        base_state='TOURING', resume_required=True)
    assert lease.expires_at == 30.0
    renewed = leases.begin(
        'robot_0', 'pause', now=20.0, duration=20.0,
        base_state='SHOULD_NOT_REPLACE', resume_required=False)
    assert renewed.base_state == 'TOURING'
    assert renewed.resume_required is True
    assert renewed.expires_at == 40.0
    assert leases.expired(39.9) == []
    expired = leases.expired(40.0)
    assert [item.robot_id for item in expired] == ['robot_0']
    assert leases.snapshot(40.0) == {}

    temporary = TemporaryMissionLease(
        mission_id='temporary-1', target_task_id='time_tunnel',
        base_task_ids=('technology_history', 'vision_hall', 'lounge'),
        skipped_task_ids=(), resume_task_id='technology_history',
        base_state='TOURING',
        started_at=10.0, safety_deadline=310.0, dwell_sec=20.0)
    assert temporary.due(309.0) is None
    assert temporary.arrive(100.0) is False
    assert temporary.snapshot(105.0)['phase'] == 'DWELLING'
    assert temporary.due(119.9) is None
    assert temporary.due(120.0) == 'dwell_completed'
    immediate = TemporaryMissionLease(
        mission_id='temporary-2', target_task_id='lounge',
        base_task_ids=('lounge',), skipped_task_ids=(),
        resume_task_id='lounge', base_state='GOING_TO_LOUNGE', started_at=1.0,
        safety_deadline=301.0, dwell_sec=0.0)
    assert immediate.arrive(10.0) is True
    assert immediate.due(10.0) == 'destination_reached'
    print('Action policy and renewable override leases: OK')


if __name__ == '__main__':
    main()
