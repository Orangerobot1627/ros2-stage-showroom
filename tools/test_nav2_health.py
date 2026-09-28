#!/usr/bin/env python3
"""Deterministic tests for the Nav2 blocked/recovery state machine."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_nav2_health import Nav2HealthTracker  # noqa: E402


def main():
    tracker = Nav2HealthTracker(
        blocked_confirm_sec=1.0, clear_confirm_sec=0.3)

    # Normal Collision Monitor slowdown while moving is not a business block.
    tracker.update_collision_state(3, 'FootprintApproach')
    tracker.update_velocity(0.18, 0.0)
    assert tracker.step(1.0, mission_active=True) is None
    assert tracker.snapshot(2.0, True)['blocked'] is False

    # A stationary intervention must persist before it is reported.
    tracker.update_velocity(0.0, 0.0)
    assert tracker.step(3.0, mission_active=True) is None
    assert tracker.step(3.8, mission_active=True) is None
    assert tracker.step(4.0, mission_active=True) == 'blocked'
    blocked = tracker.snapshot(5.5, True)
    assert blocked['blocked'] is True
    assert blocked['blocked_since_sec'] == 3.0
    assert blocked['blocked_duration_sec'] == 2.5
    assert blocked['block_count'] == 1
    assert blocked['local_planner']['state'] == 'BLOCKED'

    # Moving again is recovery; a short pulse is debounced.
    tracker.update_velocity(0.12, 0.0)
    assert tracker.step(6.0, mission_active=True) is None
    assert tracker.step(6.2, mission_active=True) is None
    assert tracker.step(6.3, mission_active=True) == 'obstacle_cleared'
    resumed = tracker.snapshot(6.3, True)
    assert resumed['blocked'] is False
    assert resumed['last_blocked_duration_sec'] == 3.3

    # A brief stop and pause do not increment the counter or emit recovery.
    tracker.update_velocity(0.0, 0.0)
    assert tracker.step(8.0, mission_active=True) is None
    assert tracker.step(8.4, mission_active=True) is None
    assert tracker.step(8.5, mission_active=True, paused=True) is None
    assert tracker.snapshot(8.5, True, paused=True)['active'] is False
    assert tracker.block_count == 1

    tracker.update_collision_state(0)
    tracker.update_velocity(0.2, 0.1)
    idle = tracker.snapshot(10.0, mission_active=False)
    assert idle['local_planner']['state'] == 'TRACKING'
    assert idle['collision_monitor']['action_name'] == 'DO_NOTHING'

    print('Nav2 obstacle health and recovery: OK')


if __name__ == '__main__':
    main()
