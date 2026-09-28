#!/usr/bin/env python3
"""Configuration-driven visitor task units for the guide route."""

from dataclasses import dataclass
from pathlib import Path

import yaml


class TaskUnitError(ValueError):
    """Raised when task-unit configuration or an edit is invalid."""


@dataclass(frozen=True)
class TaskUnit:
    """One visitor-facing section backed by a contiguous route range."""

    task_id: str
    display_name: str
    start_waypoint: str
    end_waypoint: str
    start_index: int
    end_index: int
    summary: str
    detail: str
    aliases: tuple


class TaskUnitCatalog:
    """Resolve semantic task units against one concrete waypoint route."""

    def __init__(self, task_document, route_document):
        if not isinstance(task_document, dict):
            raise TaskUnitError('Task-unit configuration must be a mapping')
        route_name = str(task_document.get('route', '')).strip()
        routes = (route_document or {}).get('routes') or {}
        route = routes.get(route_name)
        if not route_name or not isinstance(route, dict):
            raise TaskUnitError(f'Unknown task-unit route: {route_name!r}')
        waypoints = route.get('waypoints') or []
        labels = [str(item.get('label', '')).strip() for item in waypoints]
        if not labels or any(not label for label in labels):
            raise TaskUnitError('Every task route waypoint needs a label')
        if len(labels) != len(set(labels)):
            raise TaskUnitError('Task route waypoint labels must be unique')
        label_indices = {label: index for index, label in enumerate(labels)}

        units = []
        seen_ids = set()
        previous_end = -1
        for item in task_document.get('task_units') or []:
            task_id = str(item.get('id', '')).strip()
            start_label = str(item.get('start_waypoint', '')).strip()
            end_label = str(item.get('end_waypoint', '')).strip()
            if not task_id or task_id in seen_ids:
                raise TaskUnitError(f'Invalid or duplicate task id: {task_id!r}')
            if start_label not in label_indices or end_label not in label_indices:
                raise TaskUnitError(
                    f'Task {task_id!r} references an unknown waypoint')
            start_index = label_indices[start_label]
            end_index = label_indices[end_label]
            if start_index > end_index or start_index != previous_end + 1:
                raise TaskUnitError(
                    f'Task {task_id!r} must continue the previous route range')
            units.append(TaskUnit(
                task_id=task_id,
                display_name=str(item.get('display_name', task_id)).strip(),
                start_waypoint=start_label,
                end_waypoint=end_label,
                start_index=start_index,
                end_index=end_index,
                summary=str(item.get('summary', '')).strip(),
                detail=str(item.get('detail', '')).strip(),
                aliases=tuple(
                    str(alias).strip() for alias in item.get('aliases') or []
                    if str(alias).strip()),
            ))
            seen_ids.add(task_id)
            previous_end = end_index
        if not units:
            raise TaskUnitError('At least one task unit is required')
        if previous_end != len(waypoints) - 1:
            raise TaskUnitError('Task units must cover the complete guide route')

        self.route_name = route_name
        self.waypoint_labels = labels
        self.units = units
        self.units_by_id = {unit.task_id: unit for unit in units}
        self.aliases = {}
        for unit in units:
            for alias in (unit.task_id, unit.display_name, *unit.aliases):
                key = str(alias).strip().lower()
                if key in self.aliases and self.aliases[key] != unit.task_id:
                    raise TaskUnitError(f'Duplicate task alias: {alias!r}')
                self.aliases[key] = unit.task_id

    @classmethod
    def from_files(cls, task_path, route_path):
        """Load task-unit and route YAML documents."""
        task_document = yaml.safe_load(
            Path(task_path).read_text(encoding='utf-8')) or {}
        route_document = yaml.safe_load(
            Path(route_path).read_text(encoding='utf-8')) or {}
        return cls(task_document, route_document)

    def unit_index_for_waypoint(self, label=None, route_index=None):
        """Return the task-unit index containing a waypoint."""
        if route_index is None:
            try:
                route_index = self.waypoint_labels.index(str(label))
            except ValueError as exception:
                raise TaskUnitError(f'Unknown waypoint label: {label!r}') \
                    from exception
        if isinstance(route_index, bool) or not isinstance(route_index, int):
            raise TaskUnitError('Route index must be an integer')
        for index, unit in enumerate(self.units):
            if unit.start_index <= route_index <= unit.end_index:
                return index
        raise TaskUnitError(f'Route index is outside task units: {route_index}')

    def unit_for_id(self, task_id):
        """Return one configured semantic task by id."""
        try:
            return self.units_by_id[str(task_id)]
        except KeyError as exception:
            raise TaskUnitError(f'未知导览任务：{task_id!r}') from exception

    def resolve(self, value):
        """Resolve a stable task id or configured visitor-facing alias."""
        key = str(value).strip().lower()
        task_id = self.aliases.get(key, key)
        return self.unit_for_id(task_id)

    def ordered(self, task_ids):
        """Resolve, deduplicate, and restore physical showroom order."""
        requested = {self.resolve(task_id).task_id for task_id in task_ids}
        return [unit for unit in self.units if unit.task_id in requested]


class TaskUnitTracker:
    """Track and edit the current guide task without owning robot motion."""

    EDIT_INTENTS = {'skip_current', 'repeat_current', 'next_task'}

    def __init__(self, catalog):
        self.catalog = catalog
        self.current_index = None
        self.last_waypoint = None
        self.last_edit = None
        self.pending_seek_task_id = None
        self.itinerary = None
        self.skipped_task_ids = []

    @property
    def current(self):
        if self.current_index is None:
            return None
        return self.catalog.units[self.current_index]

    def start(self):
        self.current_index = 0
        self.last_waypoint = None
        self.last_edit = None
        self.pending_seek_task_id = None
        self.itinerary = None
        self.skipped_task_ids = []

    def clear(self):
        self.current_index = None
        self.last_waypoint = None
        self.last_edit = None
        self.pending_seek_task_id = None
        self.itinerary = None
        self.skipped_task_ids = []

    def set_itinerary(self, task_ids, skipped=None, last_edit='set_itinerary'):
        """Set a semantic visit list independently from its planned path."""
        units = self.catalog.ordered(task_ids)
        if not units:
            raise TaskUnitError('至少需要保留一个导览场馆')
        self.itinerary = [unit.task_id for unit in units]
        self.skipped_task_ids = list(dict.fromkeys(skipped or []))
        self.current_index = self.catalog.units.index(units[0])
        self.last_waypoint = None
        self.last_edit = last_edit
        self.pending_seek_task_id = None
        return units

    def observe_waypoint(self, label=None, reached_index=None):
        """Update the task from a 1-based route event or waypoint label."""
        if self.pending_seek_task_id is not None:
            return False
        if label is not None and label not in self.catalog.waypoint_labels:
            return False
        route_index = None
        if (label is None and isinstance(reached_index, int)
                and not isinstance(reached_index, bool)):
            route_index = reached_index - 1
        target_index = self.catalog.unit_index_for_waypoint(
            label=label, route_index=route_index)
        target = self.catalog.units[target_index]
        if self.itinerary is not None and target.task_id not in self.itinerary:
            return False
        self.current_index = target_index
        self.last_waypoint = label
        return True

    def observe_seek(self, label=None, reached_index=None, task_id=None):
        """Accept only the newest seek acknowledgement from the follower."""
        if (self.pending_seek_task_id is not None
                and task_id != self.pending_seek_task_id):
            return False
        route_index = None
        if isinstance(reached_index, int) and not isinstance(reached_index, bool):
            route_index = reached_index - 1
        target_index = self.catalog.unit_index_for_waypoint(
            label=label, route_index=route_index)
        target = self.catalog.units[target_index]
        if task_id is not None and task_id != target.task_id:
            return False
        self.current_index = target_index
        self.last_waypoint = label
        self.pending_seek_task_id = None
        return True

    def edit(self, intent):
        """Return one safe internal seek command for a task edit."""
        if intent not in self.EDIT_INTENTS:
            raise TaskUnitError(f'Unsupported task edit: {intent!r}')
        if self.current_index is None:
            raise TaskUnitError('导览尚未开始，没有可编辑的当前任务')
        target_index = self.current_index
        if intent in ('skip_current', 'next_task'):
            allowed = set(self.itinerary or (
                unit.task_id for unit in self.catalog.units))
            following = [
                index for index, unit in enumerate(self.catalog.units)
                if index > self.current_index and unit.task_id in allowed]
            if not following:
                raise TaskUnitError('当前已经是最后一个导览任务')
            target_index = following[0]
        target = self.catalog.units[target_index]
        previous = self.current
        self.current_index = target_index
        self.last_waypoint = target.start_waypoint
        self.last_edit = intent
        self.pending_seek_task_id = target.task_id
        return {
            'type': 'route_command',
            'robot_id': 'robot_0',
            'route': self.catalog.route_name,
            'action': 'seek',
            'waypoint_index': target.start_index,
            'waypoint_label': target.start_waypoint,
            'task_id': target.task_id,
            'task_edit': intent,
        }, previous, target

    def explanation(self, detailed=False):
        """Return deterministic content for direct non-LLM command clients."""
        if self.current is None:
            raise TaskUnitError('导览尚未开始，没有可讲解的当前任务')
        return self.current.detail if detailed else self.current.summary

    def snapshot(self):
        """Return compact task state for monitoring and the LLM prompt."""
        unit = self.current
        if unit is None:
            return None
        return {
            'task_id': unit.task_id,
            'display_name': unit.display_name,
            'ordinal': self.current_index + 1,
            'total': len(self.catalog.units),
            'start_waypoint': unit.start_waypoint,
            'end_waypoint': unit.end_waypoint,
            'last_waypoint': self.last_waypoint,
            'summary': unit.summary,
            'detail': unit.detail,
            'last_edit': self.last_edit,
            'pending_seek_task_id': self.pending_seek_task_id,
            'itinerary': list(self.itinerary) if self.itinerary else None,
            'skipped_task_ids': list(self.skipped_task_ids),
        }
