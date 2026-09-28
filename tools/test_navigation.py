#!/usr/bin/env python3
"""Deterministic tests for semantic route optimization."""

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_navigation import (  # noqa: E402,I100
    build_delivery_plan,
    build_guide_plan,
    GraphRoutePlanner,
    semantic_targets_from_plan,
)
from showroom_task_units import TaskUnitCatalog  # noqa: E402


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

        plan_document = build_delivery_plan(planner, {
            'robot_id': 'robot_1',
            'mission_id': f'plan-{task_id}',
            'service_target': task_id,
            'beverage': 'coffee',
        })
        nav2_route = semantic_targets_from_plan(plan_document)
        assert len(nav2_route) == len(plan_document['waypoints'])
        assert [item['label'] for item in nav2_route] == plan_document['nodes']

    vision = planner.plan_delivery('vision_hall')
    assert 'coffee_pickup_approach' in vision.nodes
    assert 'coffee_south_east' in vision.nodes
    assert vision.cost == vision.distance_m
    robotics = planner.plan_delivery('robotics_hall')
    assert robotics.distance_m < 170.0
    assert 'vision_display_north' not in robotics.nodes

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
    nav2_targets = semantic_targets_from_plan(document)
    assert len(nav2_targets) == len(document['waypoints'])
    assert [item.get('mission_phase') for item in nav2_targets
            if item.get('mission_phase') in ('pickup', 'delivery', 'standby')] == [
        'pickup', 'delivery', 'standby']
    assert [item['label'] for item in nav2_targets] == document['nodes']
    catalog = TaskUnitCatalog.from_files(
        ROOT / 'config' / 'task_units.yaml',
        ROOT / 'config' / 'routes.yaml')
    guide = build_guide_plan(planner, {
        'robot_id': 'robot_0',
        'mission_id': 'guide-7',
        'start': 'entrance',
        'task_ids': ['vision_hall', 'dance_hall', 'lounge'],
    }, catalog)
    assert guide['request_type'] == 'guide_itinerary'
    assert guide['nodes'][0] == 'stairs_clearance'
    assert guide['nodes'][-1] == 'guide_destination'
    assert guide['task_ids'] == ['vision_hall', 'dance_hall', 'lounge']
    assert 'vision_display_north' in guide['nodes']
    assert any(
        item.get('task_id') == 'vision_hall'
        for item in guide['waypoints'])
    guide_targets = semantic_targets_from_plan(guide)
    assert len(guide_targets) == len(guide['waypoints'])
    assert guide_targets[-1]['label'] == 'guide_destination'
    assert guide_targets[-1]['task_id'] == 'lounge'
    assert guide_targets[-1]['task_phase'] == 'task_end'
    route_document = yaml.safe_load(
        (ROOT / 'config' / 'routes.yaml').read_text(encoding='utf-8'))
    original_guide_labels = [
        item['label'] for item in
        route_document['routes']['guide_full_route']['waypoints'][1:]
    ]
    default_guide = build_guide_plan(planner, {
        'robot_id': 'robot_0',
        'mission_id': 'guide-default',
        'start': 'entrance',
        'task_ids': [
            'reception', 'technology_history', 'vision_hall',
            'robotics_hall', 'time_tunnel', 'dance_hall', 'lounge',
        ],
    }, catalog)
    assert default_guide['nodes'] == original_guide_labels
    resumed = build_guide_plan(planner, {
        'robot_id': 'robot_0',
        'mission_id': 'guide-8',
        'start': 'vision_display_north',
        'resume_task_id': 'vision_hall',
        'task_ids': ['vision_hall', 'lounge'],
    }, catalog)
    assert resumed['nodes'][0] != 'vision_display_north'
    assert resumed['nodes'].count('vision_hall_entry') == 0
    print(f'Navigation graph delivery routes: OK {distances}')


if __name__ == '__main__':
    main()
