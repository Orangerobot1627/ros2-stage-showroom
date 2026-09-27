#!/usr/bin/env python3
"""Deterministic tests for semantic route optimization."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_navigation import (  # noqa: E402
    build_delivery_plan,
    GraphRoutePlanner,
)


def main():
    planner = GraphRoutePlanner.from_files(
        ROOT / 'config' / 'navigation_graph.yaml',
        ROOT / 'config' / 'routes.yaml',
    )
    assert planner.frame_id == 'world'
    assert planner.standby == 'coffee_robot_standby'
    assert planner.pickup == 'coffee_pickup'

    distances = {}
    for task_id, target in planner.delivery_targets.items():
        route = planner.plan_delivery(task_id)
        assert route.nodes[0] == planner.standby
        assert route.nodes[-1] == planner.standby
        assert planner.pickup in route.nodes
        assert target in route.nodes
        assert len(route.stop_indices) == 3
        assert route.distance_m > 0.0
        distances[task_id] = route.distance_m

    vision = planner.plan_delivery('vision_hall')
    assert 'coffee_pickup_approach' in vision.nodes
    assert 'coffee_south_east' in vision.nodes
    assert vision.cost == vision.distance_m

    penalized = planner.plan(
        [planner.standby, planner.pickup],
        context={'edge_penalties': {
            'coffee_robot_standby->leave_standby': 5.0,
        }},
    )
    assert penalized.cost >= penalized.distance_m
    document = build_delivery_plan(planner, {
        'robot_id': 'robot_1',
        'mission_id': 'plan-7',
        'service_target': 'vision_hall',
        'beverage': 'coffee',
    })
    assert document['request_type'] == 'delivery'
    assert document['waypoints'][document['nodes'].index(
        'coffee_pickup')]['mission_phase'] == 'pickup'
    assert document['waypoints'][document['nodes'].index(
        'vision_inside')]['mission_phase'] == 'delivery'
    assert document['waypoints'][-1]['mission_phase'] == 'standby'
    print(f'Navigation graph delivery routes: OK {distances}')


if __name__ == '__main__':
    main()
