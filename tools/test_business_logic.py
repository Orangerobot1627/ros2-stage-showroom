#!/usr/bin/env python3
"""Deterministic tests for the showroom business state machine."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from showroom_business_logic import BusinessLogic  # noqa: E402


def route_actions(effects):
    return [
        (item['robot_id'], item['action'], item['route'])
        for item in effects
        if item.get('type') == 'route_command'
    ]


def waypoint(robot_id, label):
    return {
        'type': 'waypoint_reached',
        'robot_id': robot_id,
        'label': label,
    }


def main():
    logic = BusinessLogic(coffee_trigger='dance_loop_end')
    assert logic.snapshot()['guide_state'] == 'IDLE'

    effects = logic.handle_command({'intent': 'start_tour', 'coffee': True})
    assert route_actions(effects) == [
        ('robot_0', 'start', 'guide_full_route')]
    assert logic.guide_state == 'RECEPTION'
    assert logic.coffee_state == 'STANDBY'

    assert logic.handle_event(waypoint(
        'robot_0', 'stairs_clearance')) == []
    assert logic.guide_state == 'TOURING'
    assert logic.coffee_state == 'STANDBY'

    effects = logic.handle_event(waypoint(
        'robot_0', 'dance_loop_end'))
    assert route_actions(effects) == [
        ('robot_1', 'start', 'coffee_delivery_route')]
    assert logic.coffee_state == 'TO_PICKUP'
    assert logic.handle_event(waypoint(
        'robot_0', 'dance_loop_end')) == []

    logic.handle_event(waypoint('robot_1', 'coffee_pickup'))
    assert logic.coffee_state == 'PICKUP'
    logic.handle_event(waypoint('robot_1', 'coffee_departure'))
    assert logic.coffee_state == 'DELIVERING'
    logic.handle_event(waypoint('robot_1', 'lounge_delivery'))
    assert logic.coffee_state == 'DELIVERED'
    logic.handle_event(waypoint('robot_1', 'return_from_lounge'))
    assert logic.coffee_state == 'RETURNING'

    logic.handle_event({
        'type': 'blocked', 'robot_id': 'robot_0'})
    assert logic.guide_state == 'BLOCKED'
    logic.handle_event({
        'type': 'obstacle_cleared', 'robot_id': 'robot_0'})
    assert logic.guide_state == 'TOURING'

    effects = logic.handle_command({'intent': 'pause_tour'})
    assert route_actions(effects)[0][1] == 'pause'
    assert logic.guide_state == 'PAUSED'
    logic.handle_event(waypoint('robot_0', 'stairs_clearance'))
    assert logic.guide_state == 'PAUSED'
    effects = logic.handle_command({'intent': 'resume_tour'})
    assert route_actions(effects)[0][1] == 'resume'
    assert logic.guide_state == 'TOURING'

    effects = logic.pause_robot('robot_1')
    assert route_actions(effects)[0][1] == 'pause'
    assert logic.coffee_state == 'PAUSED'
    effects = logic.resume_robot('robot_1')
    assert route_actions(effects)[0][1] == 'resume'
    assert logic.coffee_state == 'RETURNING'

    logic.handle_event({
        'type': 'route_completed', 'robot_id': 'robot_0'})
    logic.handle_event({
        'type': 'route_completed', 'robot_id': 'robot_1'})
    assert logic.guide_state == 'COMPLETED'
    assert logic.coffee_state == 'RETURNED'

    logic = BusinessLogic(coffee_trigger='dance_loop_end')
    logic.handle_command({'intent': 'start_tour', 'coffee': False})
    assert logic.handle_event(waypoint(
        'robot_0', 'dance_loop_end')) == []
    effects = logic.handle_command({'intent': 'request_coffee'})
    assert route_actions(effects) == [
        ('robot_1', 'start', 'coffee_delivery_route')]

    effects = logic.handle_command({'intent': 'cancel_all'})
    assert len(route_actions(effects)) == 2
    assert logic.guide_state == 'CANCELLED'
    assert logic.coffee_state == 'CANCELLED'

    logic = BusinessLogic()
    effects = logic.start_default('robot_1')
    assert route_actions(effects) == [
        ('robot_1', 'start', 'coffee_delivery_route')]
    assert logic.coffee_state == 'TO_PICKUP'

    dynamic = BusinessLogic()
    dynamic.begin_delivery('vision_hall', 'coffee')
    assert dynamic.snapshot()['coffee_target'] == 'vision_hall'
    assert dynamic.coffee_state == 'TO_PICKUP'
    dynamic.handle_event({
        'type': 'waypoint_reached', 'robot_id': 'robot_1',
        'label': 'coffee_pickup', 'mission_phase': 'pickup'})
    assert dynamic.coffee_state == 'PICKUP'
    dynamic.handle_event({
        'type': 'waypoint_reached', 'robot_id': 'robot_1',
        'label': 'coffee_departure', 'mission_phase': 'depart_pickup'})
    assert dynamic.coffee_state == 'DELIVERING'
    dynamic.handle_event({
        'type': 'waypoint_reached', 'robot_id': 'robot_1',
        'label': 'vision_inside', 'mission_phase': 'delivery'})
    assert dynamic.coffee_state == 'DELIVERED'
    dynamic.handle_event({
        'type': 'waypoint_reached', 'robot_id': 'robot_1',
        'label': 'vision_hall_entry', 'mission_phase': 'returning'})
    assert dynamic.coffee_state == 'RETURNING'
    dynamic.handle_event({
        'type': 'route_completed', 'robot_id': 'robot_1'})
    assert dynamic.coffee_state == 'RETURNED'

    failed = BusinessLogic()
    failed.handle_command({'intent': 'start_tour', 'coffee': False})
    failed.handle_event({
        'type': 'route_failed', 'robot_id': 'robot_0',
        'reason': 'planner error'})
    assert failed.guide_state == 'FAILED'

    print('Business state-machine scenarios: OK')


if __name__ == '__main__':
    main()
