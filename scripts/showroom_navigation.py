#!/usr/bin/env python3
"""Semantic graph planning shared by Stage and future Nav2 adapters."""

from dataclasses import dataclass
import heapq
import math
from pathlib import Path

import yaml


class NavigationError(ValueError):
    """Raised when a named navigation request cannot be planned safely."""


@dataclass(frozen=True)
class RoutePlan:
    """One optimized path through named graph nodes."""

    nodes: tuple
    waypoints: tuple
    stop_indices: tuple
    distance_m: float
    cost: float
    cost_profile: str


class DistanceCostModel:
    """Default injectable edge-cost model for Dijkstra search."""

    def __init__(self, distance_weight=1.0, connector_penalty=0.0):
        self.distance_weight = float(distance_weight)
        self.connector_penalty = float(connector_penalty)
        if self.distance_weight <= 0.0 or self.connector_penalty < 0.0:
            raise NavigationError('Invalid route cost profile')

    def edge_cost(self, distance_m, metadata, context=None):
        """Return a non-negative edge cost; replaceable for congestion later."""
        penalty = self.connector_penalty if metadata.get('connector') else 0.0
        dynamic_penalties = (context or {}).get('edge_penalties') or {}
        edge_id = metadata.get('edge_id')
        penalty += float(dynamic_penalties.get(edge_id, 0.0))
        cost = self.distance_weight * float(distance_m) + penalty
        if cost < 0.0 or not math.isfinite(cost):
            raise NavigationError(f'Invalid edge cost for {edge_id!r}')
        return cost


class GraphRoutePlanner:
    """Plan shortest semantic routes over validated showroom corridors."""

    def __init__(self, graph_document, route_document, cost_model=None):
        if not isinstance(graph_document, dict):
            raise NavigationError('Navigation graph configuration must be a mapping')
        routes = (route_document or {}).get('routes') or {}
        self.frame_id = str(graph_document.get('frame_id', 'world'))
        self.nodes = {}
        self.edges = {}
        self.delivery_targets = dict(
            graph_document.get('delivery_targets') or {})
        service = graph_document.get('service') or {}
        self.standby = str(service.get('standby', '')).strip()
        self.pickup = str(service.get('pickup', '')).strip()

        profile_name = 'shortest'
        profile = (graph_document.get('cost_profiles') or {}).get(
            profile_name, {})
        self.cost_model = cost_model or DistanceCostModel(
            profile.get('distance_weight', 1.0),
            profile.get('connector_penalty', 0.0),
        )
        self.cost_profile = profile_name

        sources = graph_document.get('route_sources') or []
        if not sources:
            raise NavigationError('Navigation graph needs route_sources')
        for route_name in sources:
            route = routes.get(route_name)
            if not isinstance(route, dict):
                raise NavigationError(
                    f'Unknown navigation route source: {route_name!r}')
            previous = None
            for item in route.get('waypoints') or []:
                label = self._add_node(item)
                if previous is not None and previous != label:
                    self._add_edge(
                        previous, label,
                        {'route': route_name, 'connector': False})
                previous = label

        for connector in graph_document.get('connectors') or []:
            start = str(connector.get('from', '')).strip()
            goal = str(connector.get('to', '')).strip()
            if start not in self.nodes or goal not in self.nodes:
                raise NavigationError(
                    f'Connector references unknown nodes: {start!r}, {goal!r}')
            metadata = {'route': None, 'connector': True}
            self._add_edge(
                start, goal, metadata,
                bidirectional=bool(connector.get('bidirectional', True)))

        required = [self.standby, self.pickup, *self.delivery_targets.values()]
        missing = [name for name in required if name not in self.nodes]
        if missing:
            raise NavigationError(f'Unknown configured navigation nodes: {missing}')

    @classmethod
    def from_files(cls, graph_path, route_path, cost_model=None):
        """Load graph and route YAML files."""
        graph_document = yaml.safe_load(
            Path(graph_path).read_text(encoding='utf-8')) or {}
        route_document = yaml.safe_load(
            Path(route_path).read_text(encoding='utf-8')) or {}
        return cls(graph_document, route_document, cost_model=cost_model)

    def _add_node(self, item):
        if not isinstance(item, dict):
            raise NavigationError('Route waypoint must be a mapping')
        label = str(item.get('label', '')).strip()
        if not label:
            raise NavigationError('Navigation waypoint needs a label')
        x = float(item.get('x'))
        y = float(item.get('y'))
        if not math.isfinite(x) or not math.isfinite(y):
            raise NavigationError(f'Waypoint {label!r} has invalid coordinates')
        existing = self.nodes.get(label)
        if existing is not None and (
                abs(existing['x'] - x) > 1e-6
                or abs(existing['y'] - y) > 1e-6):
            raise NavigationError(f'Waypoint label has conflicting poses: {label}')
        self.nodes[label] = {'x': x, 'y': y, 'label': label}
        self.edges.setdefault(label, {})
        return label

    def _add_edge(self, start, goal, metadata, bidirectional=True):
        a = self.nodes[start]
        b = self.nodes[goal]
        distance = math.hypot(b['x'] - a['x'], b['y'] - a['y'])
        if distance <= 0.0:
            distance = 0.001

        def insert(source, target):
            edge_metadata = dict(metadata)
            edge_metadata['edge_id'] = f'{source}->{target}'
            existing = self.edges[source].get(target)
            if existing is None or distance < existing[0]:
                self.edges[source][target] = (distance, edge_metadata)

        insert(start, goal)
        if bidirectional:
            insert(goal, start)

    def target_for_task(self, task_id):
        """Resolve a semantic guide task to its accessible delivery node."""
        target = self.delivery_targets.get(task_id)
        if target is None:
            raise NavigationError(f'No delivery target for task: {task_id!r}')
        return target

    def _shortest_segment(self, start, goal, context=None):
        if start not in self.nodes or goal not in self.nodes:
            raise NavigationError(f'Unknown route endpoint: {start!r} -> {goal!r}')
        queue = [(0.0, 0.0, start)]
        best_cost = {start: 0.0}
        best_distance = {start: 0.0}
        previous = {}
        while queue:
            cost, distance, current = heapq.heappop(queue)
            if cost > best_cost.get(current, math.inf):
                continue
            if current == goal:
                break
            for neighbor, (edge_distance, metadata) in self.edges[current].items():
                edge_cost = self.cost_model.edge_cost(
                    edge_distance, metadata, context=context)
                candidate = cost + edge_cost
                if candidate + 1e-9 < best_cost.get(neighbor, math.inf):
                    best_cost[neighbor] = candidate
                    best_distance[neighbor] = distance + edge_distance
                    previous[neighbor] = current
                    heapq.heappush(
                        queue,
                        (candidate, distance + edge_distance, neighbor),
                    )
        if goal not in best_cost:
            raise NavigationError(f'No route from {start!r} to {goal!r}')
        nodes = [goal]
        while nodes[-1] != start:
            nodes.append(previous[nodes[-1]])
        nodes.reverse()
        return nodes, best_distance[goal], best_cost[goal]

    def plan(self, stops, context=None):
        """Optimize each leg and concatenate an ordered multi-stop mission."""
        stops = [str(item).strip() for item in stops]
        if len(stops) < 2 or any(not item for item in stops):
            raise NavigationError('A route plan needs at least two named stops')
        full_nodes = []
        stop_indices = []
        total_distance = 0.0
        total_cost = 0.0
        for start, goal in zip(stops, stops[1:]):
            segment, distance, cost = self._shortest_segment(
                start, goal, context=context)
            if full_nodes:
                segment = segment[1:]
            full_nodes.extend(segment)
            total_distance += distance
            total_cost += cost
            stop_indices.append(len(full_nodes) - 1)
        waypoints = tuple(dict(self.nodes[name]) for name in full_nodes)
        return RoutePlan(
            nodes=tuple(full_nodes),
            waypoints=waypoints,
            stop_indices=tuple(stop_indices),
            distance_m=round(total_distance, 3),
            cost=round(total_cost, 3),
            cost_profile=self.cost_profile,
        )

    def plan_delivery(self, task_id, start=None, context=None):
        """Plan standby/current -> pickup -> visitor -> standby service."""
        target = self.target_for_task(task_id)
        return self.plan(
            [start or self.standby, self.pickup, target, self.standby],
            context=context,
        )


def build_delivery_plan(planner, request):
    """Build a validated transport-neutral delivery plan document."""
    if not isinstance(request, dict):
        raise NavigationError('Navigation request must be an object')
    if request.get('robot_id') != 'robot_1':
        raise NavigationError('Drink delivery is currently assigned to robot_1')
    mission_id = str(request.get('mission_id', '')).strip()
    task_id = str(request.get('service_target', '')).strip()
    start = str(request.get('start', planner.standby)).strip()
    if not mission_id or not task_id:
        raise NavigationError('Delivery request needs mission_id and service_target')
    route = planner.plan_delivery(task_id, start=start)
    waypoints = [dict(item) for item in route.waypoints]
    pickup_index, delivery_index, standby_index = route.stop_indices
    for item in waypoints:
        item.update({
            'mission_id': mission_id,
            'service_target': task_id,
            'beverage': str(request.get('beverage', 'coffee')),
        })
    waypoints[pickup_index]['mission_phase'] = 'pickup'
    if pickup_index + 1 < len(waypoints):
        waypoints[pickup_index + 1]['mission_phase'] = 'depart_pickup'
    waypoints[delivery_index]['mission_phase'] = 'delivery'
    if delivery_index + 1 < len(waypoints):
        waypoints[delivery_index + 1]['mission_phase'] = 'returning'
    waypoints[standby_index]['mission_phase'] = 'standby'
    return {
        'type': 'navigation_plan',
        'robot_id': 'robot_1',
        'route': str(request.get('route', 'coffee_delivery_route')),
        'mission_id': mission_id,
        'request_type': 'delivery',
        'service_target': task_id,
        'beverage': str(request.get('beverage', 'coffee')),
        'frame_id': planner.frame_id,
        'cost_profile': route.cost_profile,
        'distance_m': route.distance_m,
        'cost': route.cost,
        'nodes': list(route.nodes),
        'waypoints': waypoints,
    }
