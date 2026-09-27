#!/usr/bin/env python3
"""Deterministic tests for Stage reactive obstacle bypass decisions."""

import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_local_planner import (  # noqa: E402
    ReactiveLocalPlanner,
    scan_sectors,
)


def clear(front=3.0, left=3.0, right=3.0):
    return {
        'front': front,
        'left_front': left,
        'right_front': right,
        'left_side': left,
        'right_side': right,
    }


def main():
    planner = ReactiveLocalPlanner(
        trigger_distance=0.8, clear_distance=1.0,
        pass_distance=1.0)
    assert planner.update(clear(), (0.0, 0.0, 0.0), 0.0) is None

    command = planner.update(
        clear(front=0.6, left=2.0, right=0.7),
        (0.0, 0.0, 0.0), 0.0)
    assert command.event == 'avoidance_started'
    assert command.angular > 0.0
    assert planner.snapshot()['state'] == 'TURNING'

    command = planner.update(
        clear(front=2.0, left=2.0, right=0.7),
        (0.0, 0.0, math.pi / 3), -0.8)
    assert command.event == 'avoidance_passing'
    assert command.linear > 0.0
    command = planner.update(
        clear(front=2.0, left=2.0, right=0.7),
        (1.1, 0.0, math.pi / 3), -0.8)
    assert command.event == 'avoidance_rejoining'
    assert planner.update(clear(), (1.1, 0.0, 0.4), -0.4) is None
    command = planner.update(clear(), (1.1, 0.0, 0.0), 0.1)
    assert command.event == 'obstacle_bypassed'
    assert not planner.active

    planner.reset()
    first = planner.update(
        clear(front=0.6, left=2.0, right=0.7),
        (0.0, 0.0, 0.0), 0.0)
    assert first.event == 'avoidance_started'
    planner.state = 'REJOINING'
    replanned = planner.update(
        clear(front=0.6, left=2.0, right=0.7),
        (0.5, 0.0, 0.0), 0.0)
    assert replanned.event == 'avoidance_replanned'
    assert planner.avoidance_count == 1

    ranges = [5.0] * 181
    ranges[90] = 0.4
    sectors = scan_sectors(
        ranges, -math.pi / 2, math.pi / 180, 0.05, 10.0)
    assert sectors['front'] == 0.4
    print('Reactive local obstacle planner: OK')


if __name__ == '__main__':
    main()
