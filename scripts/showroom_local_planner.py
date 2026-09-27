#!/usr/bin/env python3
"""
Small reactive local planner for the Stage waypoint backend.

The global graph still decides where the robot should go. This controller only
creates a short, sensor-driven detour and then hands control back to path
tracking. It mirrors Nav2's separation between global planning, local control,
and collision stopping without pretending to be a full Nav2 replacement.
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LocalCommand:
    linear: float
    angular: float
    event: str = None


class ReactiveLocalPlanner:
    """Turn, pass, and rejoin around a temporary 2D laser obstacle."""

    def __init__(self, trigger_distance=0.85, clear_distance=1.05,
                 emergency_distance=0.30, side_min_distance=0.48,
                 pass_distance=1.25, pass_speed=0.24, turn_speed=0.75,
                 rejoin_heading=0.22):
        self.trigger_distance = float(trigger_distance)
        self.clear_distance = float(clear_distance)
        self.emergency_distance = float(emergency_distance)
        self.side_min_distance = float(side_min_distance)
        self.pass_distance = float(pass_distance)
        self.pass_speed = float(pass_speed)
        self.turn_speed = float(turn_speed)
        self.rejoin_heading = float(rejoin_heading)
        self.reset()

    def reset(self):
        self.state = 'TRACKING'
        self.turn_direction = 0
        self.pass_start = None
        self.avoidance_count = 0
        self.last_reason = None

    @property
    def active(self):
        return self.state != 'TRACKING'

    @staticmethod
    def _travelled(start, pose):
        if start is None or pose is None:
            return 0.0
        return math.hypot(pose[0] - start[0], pose[1] - start[1])

    def _begin(self, sectors, pose, forced=False):
        continuing = self.active
        left = min(sectors['left_front'], sectors['left_side'])
        right = min(sectors['right_front'], sectors['right_side'])
        best = max(left, right)
        if not forced and best < self.side_min_distance:
            self.last_reason = 'no_safe_side'
            return LocalCommand(0.0, 0.0, 'avoidance_blocked')
        self.turn_direction = 1 if left >= right else -1
        self.state = 'TURNING'
        self.pass_start = pose
        if not continuing:
            self.avoidance_count += 1
            self.last_reason = (
                'visitor_request' if forced else 'laser_obstacle')
        return LocalCommand(
            0.0, self.turn_direction * self.turn_speed,
            'avoidance_replanned' if continuing else 'avoidance_started')

    def force(self, sectors, pose):
        """Start a requested bypass, even if the obstacle is just outside the trigger."""
        if self.active:
            return LocalCommand(0.0, 0.0)
        return self._begin(sectors, pose, forced=True)

    def update(self, sectors, pose, heading_error, forward_requested=True):
        """Return an override command, or None when route tracking owns motion."""
        front = sectors['front']
        if self.state == 'TRACKING':
            if forward_requested and front < self.trigger_distance:
                return self._begin(sectors, pose)
            return None

        if self.state == 'TURNING':
            opening = (
                sectors['left_front'] if self.turn_direction > 0
                else sectors['right_front'])
            if front >= self.clear_distance and opening >= self.trigger_distance:
                self.state = 'PASSING'
                self.pass_start = pose
                return LocalCommand(
                    self.pass_speed, 0.12 * self.turn_direction,
                    'avoidance_passing')
            return LocalCommand(0.0, self.turn_direction * self.turn_speed)

        if self.state == 'PASSING':
            if front < self.emergency_distance:
                return LocalCommand(0.0, self.turn_direction * self.turn_speed)
            obstacle_side = (
                sectors['right_side'] if self.turn_direction > 0
                else sectors['left_side'])
            correction = 0.0
            if obstacle_side < self.side_min_distance:
                correction = 0.30 * self.turn_direction
            if (self._travelled(self.pass_start, pose) >= self.pass_distance
                    and front >= self.clear_distance):
                self.state = 'REJOINING'
                return LocalCommand(0.0, 0.0, 'avoidance_rejoining')
            return LocalCommand(self.pass_speed, correction)

        if self.state == 'REJOINING':
            if front < self.trigger_distance:
                return self._begin(sectors, pose)
            if abs(heading_error) <= self.rejoin_heading:
                self.state = 'TRACKING'
                self.turn_direction = 0
                self.pass_start = None
                return LocalCommand(0.0, 0.0, 'obstacle_bypassed')
            return None

        self.reset()
        return None

    def snapshot(self):
        return {
            'state': self.state,
            'active': self.active,
            'turn_direction': (
                'left' if self.turn_direction > 0
                else 'right' if self.turn_direction < 0 else None),
            'avoidance_count': self.avoidance_count,
            'last_reason': self.last_reason,
        }


def scan_sectors(ranges, angle_min, angle_increment, range_min, range_max):
    """Reduce one laser scan into conservative local-planner sectors."""
    buckets = {
        'front': [], 'left_front': [], 'right_front': [],
        'left_side': [], 'right_side': [],
    }
    angle = float(angle_min)
    for value in ranges:
        if math.isfinite(value) and range_min <= value <= range_max:
            degrees = math.degrees(angle)
            if abs(degrees) <= 25.0:
                buckets['front'].append(value)
            if 20.0 <= degrees <= 65.0:
                buckets['left_front'].append(value)
            if -65.0 <= degrees <= -20.0:
                buckets['right_front'].append(value)
            if 55.0 <= degrees <= 115.0:
                buckets['left_side'].append(value)
            if -115.0 <= degrees <= -55.0:
                buckets['right_side'].append(value)
        angle += angle_increment

    def conservative(values):
        if not values:
            return math.inf
        ordered = sorted(values)
        # A low percentile ignores one noisy ray but still reacts to an object
        # occupying a meaningful part of the sector.
        return ordered[min(len(ordered) - 1, max(0, len(ordered) // 8))]

    result = {name: conservative(values) for name, values in buckets.items()}
    # Emergency stopping must remain conservative even for a single return.
    result['front'] = min(buckets['front'], default=math.inf)
    return result
