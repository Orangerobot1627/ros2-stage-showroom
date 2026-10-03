#!/usr/bin/env python3
"""Pure state machines for Nav2 progress and obstacle recovery telemetry."""

import math


ACTION_NAMES = {
    0: 'DO_NOTHING',
    1: 'STOP',
    2: 'SLOWDOWN',
    3: 'APPROACH',
    4: 'LIMIT',
}


class Nav2ActionProgress:
    """Track one mission's NavigateToPose feedback without ROS dependencies."""

    def __init__(self):
        self.generation = 0
        self.completed_recoveries = 0
        self._reset_target()

    def _reset_target(self):
        self.action_active = False
        self.navigation_time_sec = None
        self.estimated_time_remaining_sec = None
        self.distance_remaining_m = None
        self.target_recoveries = 0
        self.feedback_received_at = None

    def reset_mission(self):
        """Invalidate late callbacks and clear mission-level counters."""
        self.generation += 1
        self.completed_recoveries = 0
        self._reset_target()

    def begin_target(self):
        """Start a new action generation and return its callback token."""
        self.generation += 1
        self._reset_target()
        self.action_active = True
        return self.generation

    @staticmethod
    def _nonnegative(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number < 0.0:
            return None
        return number

    def update(self, generation, *, navigation_time_sec,
               estimated_time_remaining_sec, distance_remaining_m,
               recovery_count, received_at):
        """Accept feedback only for the currently active action goal."""
        if generation != self.generation or not self.action_active:
            return False
        self.navigation_time_sec = self._nonnegative(navigation_time_sec)
        self.estimated_time_remaining_sec = self._nonnegative(
            estimated_time_remaining_sec)
        self.distance_remaining_m = self._nonnegative(distance_remaining_m)
        try:
            self.target_recoveries = max(0, int(recovery_count))
        except (TypeError, ValueError):
            self.target_recoveries = 0
        self.feedback_received_at = self._nonnegative(received_at)
        return True

    def finish_target(self, generation):
        """Commit the current action's recovery count once it terminates."""
        if generation != self.generation or not self.action_active:
            return False
        self.completed_recoveries += self.target_recoveries
        self.target_recoveries = 0
        self.action_active = False
        return True

    def snapshot(self, now):
        feedback_age = None
        if self.feedback_received_at is not None:
            feedback_age = max(0.0, float(now) - self.feedback_received_at)
        return {
            'action_active': self.action_active,
            'navigation_time_sec': self.navigation_time_sec,
            'estimated_time_remaining_sec': (
                self.estimated_time_remaining_sec),
            'distance_remaining_m': self.distance_remaining_m,
            'number_of_recoveries': (
                self.completed_recoveries + self.target_recoveries),
            'target_recoveries': self.target_recoveries,
            'feedback_age_sec': feedback_age,
        }


class Nav2HealthTracker:
    """Debounce Nav2 safety intervention into business-level block events."""

    def __init__(self, blocked_confirm_sec=1.0, clear_confirm_sec=0.35,
                 linear_stopped_threshold=0.02,
                 angular_stopped_threshold=0.05):
        self.blocked_confirm_sec = max(0.0, float(blocked_confirm_sec))
        self.clear_confirm_sec = max(0.0, float(clear_confirm_sec))
        self.linear_stopped_threshold = max(
            0.0, float(linear_stopped_threshold))
        self.angular_stopped_threshold = max(
            0.0, float(angular_stopped_threshold))
        self.action_type = 0
        self.polygon_name = ''
        self.linear_x = 0.0
        self.angular_z = 0.0
        self.blocked = False
        self.blocked_since = None
        self.block_candidate_since = None
        self.clear_candidate_since = None
        self.last_blocked_duration = 0.0
        self.block_count = 0

    @property
    def action_name(self):
        return ACTION_NAMES.get(self.action_type, f'UNKNOWN_{self.action_type}')

    @property
    def safety_active(self):
        return self.action_type != 0

    @property
    def stopped(self):
        return (
            abs(self.linear_x) <= self.linear_stopped_threshold
            and abs(self.angular_z) <= self.angular_stopped_threshold
        )

    def update_collision_state(self, action_type, polygon_name=''):
        self.action_type = int(action_type)
        self.polygon_name = str(polygon_name or '')

    def update_velocity(self, linear_x, angular_z):
        self.linear_x = float(linear_x)
        self.angular_z = float(angular_z)

    def reset_transient(self):
        """Drop one mission's timing state while preserving cumulative count."""
        self.blocked = False
        self.blocked_since = None
        self.block_candidate_since = None
        self.clear_candidate_since = None

    def step(self, now, mission_active, paused=False):
        """Advance the detector and return blocked/obstacle_cleared or None."""
        now = float(now)
        if not mission_active or paused:
            self.reset_transient()
            return None

        block_candidate = self.safety_active and self.stopped
        if not self.blocked:
            self.clear_candidate_since = None
            if not block_candidate:
                self.block_candidate_since = None
                return None
            if self.block_candidate_since is None:
                self.block_candidate_since = now
            if (now - self.block_candidate_since + 1e-9
                    < self.blocked_confirm_sec):
                return None
            self.blocked = True
            self.blocked_since = self.block_candidate_since
            self.block_candidate_since = None
            self.block_count += 1
            return 'blocked'

        cleared_candidate = not self.safety_active or not self.stopped
        if not cleared_candidate:
            self.clear_candidate_since = None
            return None
        if self.clear_candidate_since is None:
            self.clear_candidate_since = now
        if now - self.clear_candidate_since + 1e-9 < self.clear_confirm_sec:
            return None
        self.last_blocked_duration = max(0.0, now - self.blocked_since)
        self.blocked = False
        self.blocked_since = None
        self.clear_candidate_since = None
        return 'obstacle_cleared'

    def snapshot(self, now, mission_active, paused=False):
        duration = 0.0
        if self.blocked and self.blocked_since is not None:
            duration = max(0.0, float(now) - self.blocked_since)
        if self.blocked:
            planner_state = 'BLOCKED'
        elif self.safety_active:
            planner_state = f'COLLISION_{self.action_name}'
        else:
            planner_state = 'TRACKING'
        return {
            'active': bool(mission_active and not paused),
            'blocked': self.blocked,
            'blocked_since_sec': self.blocked_since,
            'blocked_duration_sec': duration,
            'last_blocked_duration_sec': self.last_blocked_duration,
            'block_count': self.block_count,
            'collision_monitor': {
                'action_type': self.action_type,
                'action_name': self.action_name,
                'polygon_name': self.polygon_name,
            },
            'local_planner': {
                'state': planner_state,
                'active': self.safety_active,
                'avoidance_count': self.block_count,
            },
        }
