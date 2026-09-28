#!/usr/bin/env python3
"""Pure business state machine for the showroom robot service."""


ACTIVE_GUIDE_STATES = {
    'RECEPTION',
    'TOURING',
    'GOING_TO_LOUNGE',
    'PAUSED',
    'BLOCKED',
}

ACTIVE_COFFEE_STATES = {
    'TO_PICKUP',
    'PICKUP',
    'DELIVERING',
    'DELIVERED',
    'RETURNING',
    'PAUSED',
    'BLOCKED',
}


class BusinessLogic:
    """Translate visitor intents and robot events into route commands."""

    def __init__(self, coffee_trigger='tunnel_center_south',
                 default_routes=None):
        self.coffee_trigger = coffee_trigger
        self.default_routes = {
            'robot_0': 'guide_full_route',
            'robot_1': 'coffee_delivery_route',
        }
        if default_routes:
            self.default_routes.update(default_routes)
        self.reset()

    def reset(self):
        self.guide_state = 'IDLE'
        self.coffee_state = 'STANDBY'
        self.coffee_requested = False
        self.coffee_trigger_reached = False
        self.coffee_target = None
        self.beverage = None
        self.blocked_from = {}
        self.paused_from = {}

    def snapshot(self):
        return {
            'guide_state': self.guide_state,
            'coffee_state': self.coffee_state,
            'coffee_requested': self.coffee_requested,
            'coffee_trigger': self.coffee_trigger,
            'coffee_trigger_reached': self.coffee_trigger_reached,
            'coffee_target': self.coffee_target,
            'beverage': self.beverage,
        }

    @staticmethod
    def route_command(robot_id, action, route):
        return {
            'type': 'route_command',
            'robot_id': robot_id,
            'action': action,
            'route': route,
        }

    def route_for(self, robot_id):
        """Return the configured default route for one robot."""
        return self.default_routes[robot_id]

    def state_for(self, robot_id):
        """Return the business state associated with one robot."""
        if robot_id == 'robot_0':
            return self.guide_state
        if robot_id == 'robot_1':
            return self.coffee_state
        raise ValueError(f'Unknown robot: {robot_id!r}')

    def pause_robot(self, robot_id):
        """Pause an active default mission without losing route progress."""
        state = self.state_for(robot_id)
        if state == 'PAUSED':
            return []
        active_states = (
            ACTIVE_GUIDE_STATES if robot_id == 'robot_0'
            else ACTIVE_COFFEE_STATES)
        if state not in active_states:
            raise ValueError(f'{robot_id} has no active mission to pause')
        if state == 'BLOCKED':
            previous = self.blocked_from.get(robot_id, state)
        else:
            previous = state
        self.paused_from[robot_id] = previous
        self.blocked_from.pop(robot_id, None)
        if robot_id == 'robot_0':
            self.guide_state = 'PAUSED'
        else:
            self.coffee_state = 'PAUSED'
        return [self.route_command(
            robot_id, 'pause', self.route_for(robot_id))]

    def resume_robot(self, robot_id):
        """Resume the mission that was active before a human override."""
        state = self.state_for(robot_id)
        if state != 'PAUSED':
            raise ValueError(f'{robot_id} is not paused')
        previous = self.paused_from.pop(robot_id, None)
        if robot_id == 'robot_0':
            self.guide_state = previous or 'TOURING'
        else:
            self.coffee_state = previous or 'DELIVERING'
        return [self.route_command(
            robot_id, 'resume', self.route_for(robot_id))]

    def start_default(self, robot_id):
        """Start a robot's configured default mission."""
        if robot_id == 'robot_0':
            if self.guide_state in ACTIVE_GUIDE_STATES:
                raise ValueError('A guide tour is already active')
            self.guide_state = 'RECEPTION'
            self.coffee_trigger_reached = False
        elif robot_id == 'robot_1':
            if self.coffee_state in ACTIVE_COFFEE_STATES:
                raise ValueError('A coffee mission is already active')
            self.coffee_requested = True
            self.coffee_target = 'lounge'
            self.beverage = 'coffee'
            self.coffee_state = 'TO_PICKUP'
        else:
            raise ValueError(f'Unknown robot: {robot_id!r}')
        self.paused_from.pop(robot_id, None)
        self.blocked_from.pop(robot_id, None)
        return [self.route_command(
            robot_id, 'start', self.route_for(robot_id))]

    def cancel_robot(self, robot_id):
        """Cancel one robot mission and discard its suspended state."""
        if robot_id == 'robot_0':
            self.guide_state = 'CANCELLED'
        elif robot_id == 'robot_1':
            self.coffee_state = 'CANCELLED'
        else:
            raise ValueError(f'Unknown robot: {robot_id!r}')
        self.paused_from.pop(robot_id, None)
        self.blocked_from.pop(robot_id, None)
        return [self.route_command(
            robot_id, 'cancel', self.route_for(robot_id))]

    def dispatch_coffee_if_ready(self):
        if not self.coffee_requested or not self.coffee_trigger_reached:
            return []
        if self.coffee_state != 'STANDBY':
            return []
        self.coffee_state = 'TO_PICKUP'
        return [self.route_command(
            'robot_1', 'start', self.route_for('robot_1'))]

    def begin_delivery(self, target, beverage='coffee'):
        """Reserve robot_1 for one optimized pickup/dropoff mission."""
        if self.coffee_state in ACTIVE_COFFEE_STATES:
            raise ValueError('A drink delivery mission is already active')
        self.coffee_requested = True
        self.coffee_target = str(target)
        self.beverage = str(beverage)
        self.coffee_state = 'TO_PICKUP'
        self.paused_from.pop('robot_1', None)
        self.blocked_from.pop('robot_1', None)

    def handle_command(self, message):
        intent = message.get('intent') or message.get('command')
        if intent == 'start_tour':
            if self.guide_state in ACTIVE_GUIDE_STATES:
                raise ValueError('A guide tour is already active')
            self.guide_state = 'RECEPTION'
            self.coffee_state = 'STANDBY'
            self.coffee_requested = bool(message.get('coffee', True))
            self.coffee_target = 'lounge' if self.coffee_requested else None
            self.beverage = 'coffee' if self.coffee_requested else None
            self.coffee_trigger_reached = False
            self.blocked_from.clear()
            self.paused_from.clear()
            return [self.route_command(
                'robot_0', 'start', self.route_for('robot_0'))]

        if intent == 'request_coffee':
            self.coffee_requested = True
            self.coffee_target = self.coffee_target or 'lounge'
            self.beverage = self.beverage or 'coffee'
            return self.dispatch_coffee_if_ready()

        if intent == 'pause_tour':
            return self.pause_robot('robot_0')

        if intent == 'resume_tour':
            return self.resume_robot('robot_0')

        if intent == 'cancel_all':
            return (
                self.cancel_robot('robot_0')
                + self.cancel_robot('robot_1'))

        if intent == 'reset':
            effects = [
                self.route_command(
                    'robot_0', 'cancel', self.route_for('robot_0')),
                self.route_command(
                    'robot_1', 'cancel', self.route_for('robot_1')),
            ]
            self.reset()
            return effects

        raise ValueError(f'Unsupported intent: {intent!r}')

    def handle_event(self, message):
        event_type = message.get('type')
        robot_id = message.get('robot_id')

        if event_type == 'blocked':
            if robot_id == 'robot_0' and self.guide_state != 'BLOCKED':
                self.blocked_from[robot_id] = self.guide_state
                self.guide_state = 'BLOCKED'
            if robot_id == 'robot_1' and self.coffee_state != 'BLOCKED':
                self.blocked_from[robot_id] = self.coffee_state
                self.coffee_state = 'BLOCKED'
            return []

        if event_type == 'obstacle_cleared':
            previous = self.blocked_from.pop(robot_id, None)
            if robot_id == 'robot_0' and previous is not None:
                self.guide_state = previous
            if robot_id == 'robot_1' and previous is not None:
                self.coffee_state = previous
            return []

        if event_type == 'route_cancelled':
            if robot_id == 'robot_0':
                self.guide_state = 'CANCELLED'
            if robot_id == 'robot_1':
                self.coffee_state = 'CANCELLED'
            return []

        if event_type == 'route_completed':
            if robot_id == 'robot_0':
                self.guide_state = 'COMPLETED'
            if robot_id == 'robot_1':
                self.coffee_state = 'RETURNED'
            return []

        if event_type in ('route_failed', 'route_command_rejected'):
            if robot_id == 'robot_0':
                self.guide_state = 'FAILED'
            if robot_id == 'robot_1':
                self.coffee_state = 'FAILED'
            return []

        if event_type != 'waypoint_reached':
            return []

        label = message.get('label')
        if robot_id == 'robot_0':
            next_state = None
            if label == 'entrance':
                next_state = 'RECEPTION'
            elif label == 'stairs_clearance':
                next_state = 'TOURING'
            elif label == self.coffee_trigger:
                self.coffee_trigger_reached = True
            elif label == 'lounge_top_entry':
                next_state = 'GOING_TO_LOUNGE'
            elif label == 'guide_destination':
                next_state = 'AT_LOUNGE'
            if next_state is not None:
                if self.guide_state == 'PAUSED':
                    self.paused_from[robot_id] = next_state
                else:
                    self.guide_state = next_state
            return self.dispatch_coffee_if_ready()

        if robot_id == 'robot_1':
            next_state = None
            mission_phase = message.get('mission_phase')
            if mission_phase == 'pickup' or label == 'coffee_pickup':
                next_state = 'PICKUP'
            elif mission_phase == 'depart_pickup' or label == 'coffee_departure':
                next_state = 'DELIVERING'
            elif mission_phase == 'delivery' or label == 'lounge_delivery':
                next_state = 'DELIVERED'
            elif mission_phase == 'returning' or label == 'return_from_lounge':
                next_state = 'RETURNING'
            if next_state is not None:
                if self.coffee_state == 'PAUSED':
                    self.paused_from[robot_id] = next_state
                else:
                    self.coffee_state = next_state
        return []
