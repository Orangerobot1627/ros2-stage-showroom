#!/usr/bin/env python3
"""Deterministic tests for the Nav2 blocked/recovery state machine."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_nav2_health import (  # noqa: E402
    Nav2ActionProgress,
    Nav2HealthTracker,
)


def main():
    progress = Nav2ActionProgress()
    first_goal = progress.begin_target()
    assert progress.update(
        first_goal,
        navigation_time_sec=4.5,
        estimated_time_remaining_sec=8.25,
        distance_remaining_m=3.75,
        recovery_count=1,
        received_at=10.0,
    ) is True
    active_progress = progress.snapshot(10.2)
    assert active_progress['action_active'] is True
    assert active_progress['distance_remaining_m'] == 3.75
    assert active_progress['estimated_time_remaining_sec'] == 8.25
    assert active_progress['number_of_recoveries'] == 1
    assert round(active_progress['feedback_age_sec'], 6) == 0.2

    # Completed target recoveries remain cumulative across the next waypoint.
    assert progress.finish_target(first_goal) is True
    second_goal = progress.begin_target()
    assert progress.update(
        second_goal,
        navigation_time_sec=1.0,
        estimated_time_remaining_sec=float('inf'),
        distance_remaining_m=-1.0,
        recovery_count=2,
        received_at=12.0,
    ) is True
    second_progress = progress.snapshot(12.0)
    assert second_progress['distance_remaining_m'] is None
    assert second_progress['estimated_time_remaining_sec'] is None
    assert second_progress['number_of_recoveries'] == 3

    # A late callback from an old goal cannot overwrite the current one.
    assert progress.update(
        first_goal,
        navigation_time_sec=99.0,
        estimated_time_remaining_sec=99.0,
        distance_remaining_m=99.0,
        recovery_count=99,
        received_at=13.0,
    ) is False
    assert progress.snapshot(13.0)['number_of_recoveries'] == 3

    progress.reset_mission()
    reset_progress = progress.snapshot(14.0)
    assert reset_progress['action_active'] is False
    assert reset_progress['distance_remaining_m'] is None
    assert reset_progress['number_of_recoveries'] == 0

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

    print('Nav2 action progress, obstacle health, and recovery: OK')


if __name__ == '__main__':
    main()
