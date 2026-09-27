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
    print('Action policy and renewable override leases: OK')


if __name__ == '__main__':
    main()
