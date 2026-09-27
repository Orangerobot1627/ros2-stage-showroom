#!/usr/bin/env python3
"""Configuration and lease bookkeeping for human task overrides."""

from dataclasses import dataclass
from pathlib import Path

import yaml


class ActionPolicyError(ValueError):
    """Raised when an action policy or requested action is invalid."""


class ActionPolicy:
    """Validated mapping from human action names to robot missions."""

    def __init__(self, document):
        if not isinstance(document, dict):
            raise ActionPolicyError('Action policy must be a mapping')
        override = document.get('override') or {}
        self.default_duration = float(
            override.get('default_duration_sec', 20.0))
        self.min_duration = float(override.get('min_duration_sec', 2.0))
        self.max_duration = float(override.get('max_duration_sec', 120.0))
        self.auto_resume = bool(override.get('auto_resume', True))
        if not 0.0 < self.min_duration <= self.default_duration:
            raise ActionPolicyError('Invalid minimum/default override duration')
        if self.default_duration > self.max_duration:
            raise ActionPolicyError('Default override exceeds maximum duration')

        robots = document.get('robots') or {}
        actions = document.get('actions') or {}
        if not robots or not actions:
            raise ActionPolicyError('Action policy needs robots and actions')
        self.robots = {}
        self.aliases = {}
        for name, specification in robots.items():
            robot_id = str(specification.get('robot_id', '')).strip()
            route = str(specification.get('default_route', '')).strip()
            if not robot_id or not route:
                raise ActionPolicyError(
                    f'Robot {name!r} needs robot_id and default_route')
            self.robots[name] = {
                'robot_id': robot_id,
                'display_name': str(
                    specification.get('display_name', name)),
                'default_route': route,
            }
            for alias in [name, robot_id] + list(
                    specification.get('aliases') or []):
                self.aliases[str(alias).strip().lower()] = name
        self.actions = actions

    @classmethod
    def from_file(cls, path):
        """Load one YAML action policy."""
        document = yaml.safe_load(
            Path(path).read_text(encoding='utf-8')) or {}
        return cls(document)

    @property
    def default_routes(self):
        """Return routes indexed by concrete robot id."""
        return {
            item['robot_id']: item['default_route']
            for item in self.robots.values()
        }

    def resolve_robots(self, target):
        """Resolve guide/coffee/all and configured aliases to robot ids."""
        target = str(target).strip().lower()
        if target == 'all':
            return [item['robot_id'] for item in self.robots.values()]
        name = self.aliases.get(target)
        if name is None:
            raise ActionPolicyError(f'Unknown robot target: {target!r}')
        return [self.robots[name]['robot_id']]

    def validate_action(self, action, target):
        """Validate one configured action for its canonical target."""
        action = str(action).strip().lower()
        specification = self.actions.get(action)
        if not isinstance(specification, dict):
            raise ActionPolicyError(f'Unknown robot action: {action!r}')
        allowed = specification.get('allowed_robots') or []
        canonical = 'all' if str(target).lower() == 'all' else self.aliases.get(
            str(target).strip().lower())
        if canonical not in allowed:
            raise ActionPolicyError(
                f'Action {action!r} is not allowed for {target!r}')
        return action

    def duration(self, requested=None):
        """Use the configured default and clamp visitor durations."""
        value = self.default_duration if requested is None else float(requested)
        return max(self.min_duration, min(self.max_duration, value))


@dataclass
class OverrideLease:
    """One temporary human override of a robot's default mission."""

    robot_id: str
    action: str
    started_at: float
    expires_at: float
    base_state: str
    resume_required: bool


class OverrideLeaseBook:
    """Track renewable override leases independently of ROS time."""

    def __init__(self):
        self._leases = {}

    def get(self, robot_id):
        """Return the active lease for one robot, if any."""
        return self._leases.get(robot_id)

    def begin(self, robot_id, action, now, duration, base_state,
              resume_required):
        """Start or renew a lease while preserving its original base state."""
        existing = self._leases.get(robot_id)
        if existing is not None:
            existing.action = action
            existing.expires_at = now + duration
            return existing
        lease = OverrideLease(
            robot_id=robot_id,
            action=action,
            started_at=now,
            expires_at=now + duration,
            base_state=base_state,
            resume_required=bool(resume_required),
        )
        self._leases[robot_id] = lease
        return lease

    def release(self, robot_id):
        """Remove and return a robot lease."""
        return self._leases.pop(robot_id, None)

    def clear(self):
        """Remove every active lease."""
        leases = list(self._leases.values())
        self._leases.clear()
        return leases

    def expired(self, now):
        """Remove and return all leases whose wall-clock deadline passed."""
        result = []
        for robot_id, lease in list(self._leases.items()):
            if now >= lease.expires_at:
                result.append(self._leases.pop(robot_id))
        return result

    def snapshot(self, now):
        """Return JSON-compatible current override status."""
        return {
            robot_id: {
                'action': lease.action,
                'base_state': lease.base_state,
                'remaining_sec': round(
                    max(0.0, lease.expires_at - now), 3),
                'resume_required': lease.resume_required,
            }
            for robot_id, lease in self._leases.items()
        }
