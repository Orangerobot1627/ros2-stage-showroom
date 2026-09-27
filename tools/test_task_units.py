#!/usr/bin/env python3
"""Deterministic tests for semantic guide task units."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_task_units import (  # noqa: E402
    TaskUnitCatalog,
    TaskUnitError,
    TaskUnitTracker,
)


def main():
    catalog = TaskUnitCatalog.from_files(
        ROOT / 'config' / 'task_units.yaml',
        ROOT / 'config' / 'routes.yaml',
    )
    assert catalog.route_name == 'guide_full_route'
    assert len(catalog.units) == 7
    assert catalog.units[0].task_id == 'reception'
    assert catalog.units[-1].task_id == 'lounge'
    assert catalog.units[-1].end_index == 64
    assert catalog.resolve('视觉馆').task_id == 'vision_hall'
    assert [unit.task_id for unit in catalog.ordered(
        ['舞蹈馆', 'vision_hall'])] == ['vision_hall', 'dance_hall']

    tracker = TaskUnitTracker(catalog)
    assert tracker.snapshot() is None
    tracker.start()
    assert tracker.snapshot()['display_name'] == '入馆接待'
    tracker.observe_waypoint('vision_display_north', reached_index=15)
    assert tracker.current.task_id == 'vision_hall'

    command, previous, target = tracker.edit('skip_current')
    assert previous.task_id == 'vision_hall'
    assert target.task_id == 'robotics_hall'
    assert command == {
        'type': 'route_command',
        'robot_id': 'robot_0',
        'route': 'guide_full_route',
        'action': 'seek',
        'waypoint_index': 23,
        'waypoint_label': 'robotics_entry_approach',
        'task_id': 'robotics_hall',
        'task_edit': 'skip_current',
    }
    command, _, target = tracker.edit('repeat_current')
    assert target.task_id == 'robotics_hall'
    assert command['waypoint_index'] == 23
    assert tracker.snapshot()['pending_seek_task_id'] == 'robotics_hall'
    assert not tracker.observe_seek(
        'vision_hall_entry', reached_index=12, task_id='vision_hall')
    assert tracker.current.task_id == 'robotics_hall'
    assert tracker.observe_seek(
        'robotics_entry_approach', reached_index=24,
        task_id='robotics_hall')
    assert tracker.snapshot()['pending_seek_task_id'] is None
    assert '感知、决策、规划与执行' in tracker.explanation(detailed=False)
    assert 'ROS 2' in tracker.explanation(detailed=True)

    tracker.start()
    tracker.edit('skip_current')
    tracker.edit('next_task')
    assert tracker.current.task_id == 'vision_hall'
    assert not tracker.observe_seek(
        'coffee_south_east', reached_index=3,
        task_id='technology_history')
    assert tracker.current.task_id == 'vision_hall'
    assert tracker.observe_seek(
        'vision_hall_entry', reached_index=12, task_id='vision_hall')

    tracker.observe_waypoint('guide_destination', reached_index=65)
    try:
        tracker.edit('next_task')
    except TaskUnitError:
        pass
    else:
        raise AssertionError('Advancing past the final task must be rejected')
    tracker.clear()
    assert tracker.snapshot() is None
    tracker.start()
    tracker.set_itinerary(
        ['vision_hall', 'lounge'], skipped=['robotics_hall'])
    assert tracker.snapshot()['itinerary'] == ['vision_hall', 'lounge']
    assert tracker.snapshot()['skipped_task_ids'] == ['robotics_hall']
    assert not tracker.observe_waypoint('robotics_inside', reached_index=2)
    assert tracker.current.task_id == 'vision_hall'
    print('Semantic guide task units and task editing: OK')


if __name__ == '__main__':
    main()
