#!/usr/bin/env python3
"""Static validation for demo_stage assets; does not require a ROS installation."""

import ast
import math
from pathlib import Path
import re
from types import SimpleNamespace
import xml.etree.ElementTree as ET

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


ROOT = Path(__file__).resolve().parents[1]


def load_generator():
    source = ROOT / 'tools' / 'generate_showroom_assets.py'
    namespace = {'__file__': str(source), '__name__': 'showroom_assets'}
    code = compile(source.read_text(encoding='utf-8'), str(source), 'exec')
    exec(code, namespace)
    return SimpleNamespace(**namespace)


def main():
    python_files = sorted(ROOT.rglob('*.py'))
    for path in python_files:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))

    yaml_files = sorted(ROOT.rglob('*.yaml'))
    for path in yaml_files:
        text = path.read_text(encoding='utf-8')
        if '\t' in text or ':' not in text:
            raise ValueError(f'Invalid basic YAML structure: {path}')
        if yaml is not None:
            yaml.safe_load(text)

    ET.parse(ROOT / 'package.xml')

    includes = []
    simulation_intervals = {}
    for world_name in ('showroom_final.world', 'showroom_nav2.world'):
        world = ROOT / 'world' / world_name
        world_text = world.read_text(encoding='utf-8')
        if world_text.count('(') != world_text.count(')'):
            raise ValueError(f'Unbalanced parentheses in {world_name}')
        if not re.search(r'^paused\s+0\s*$', world_text, re.MULTILINE):
            raise ValueError(
                f'{world_name} must start unpaused for headless operation')
        if not re.search(
                r'^speedup\s+[0-9.]+\s*$', world_text, re.MULTILINE):
            raise ValueError(
                f'{world_name} must declare an explicit speedup')
        interval_match = re.search(
            r'^interval_sim\s+([0-9]+)\s*$', world_text, re.MULTILINE)
        if interval_match is None:
            raise ValueError(f'{world_name} must declare interval_sim')
        simulation_intervals[world_name] = int(interval_match.group(1))
        world_includes = re.findall(r'include\s+"([^"]+)"', world_text)
        missing = [
            name for name in world_includes
            if not (world.parent / name).is_file()]
        if missing:
            raise FileNotFoundError(
                f'Missing Stage includes in {world_name}: {missing}')
        includes.extend(world_includes)

    robot_models = (
        ROOT / 'world' / 'include' / 'showroom_robots.inc').read_text(
            encoding='utf-8')
    position_interval_match = re.search(
        r'^\s*update_interval\s+([0-9]+)\s*$',
        robot_models, re.MULTILINE)
    if position_interval_match is None:
        raise ValueError(
            'showroom_diff_base must declare update_interval explicitly')
    position_interval = int(position_interval_match.group(1))
    odom_error_match = re.search(
        r'^\s*odom_error\s+\[\s*([^]]+)\]\s*$',
        robot_models, re.MULTILINE)
    if odom_error_match is None:
        raise ValueError('showroom_diff_base must declare odom_error')
    odom_errors = [
        float(value) for value in odom_error_match.group(1).split()]
    if len(odom_errors) != 4 or any(odom_errors):
        raise ValueError(
            'Fixed map->odom requires deterministic zero Stage odom_error')
    mismatched_worlds = [
        name for name, interval in simulation_intervals.items()
        if interval != position_interval]
    if mismatched_worlds:
        raise ValueError(
            'Stage position update_interval must equal interval_sim; '
            f'position={position_interval}, worlds={simulation_intervals}')

    test_obstacles = ROOT / 'world' / 'include' / 'showroom_test_obstacles.inc'
    obstacle_text = test_obstacles.read_text(encoding='utf-8')
    required_obstacle_properties = {
        'gui_move': r'^\s*gui_move\s+1\s*$',
        'obstacle_return': r'^\s*obstacle_return\s+1\s*$',
        'ranger_return': r'^\s*ranger_return\s+1\s*$',
    }
    missing_properties = [
        name for name, pattern in required_obstacle_properties.items()
        if not re.search(pattern, obstacle_text, re.MULTILINE)
    ]
    if missing_properties:
        raise ValueError(
            f'Test obstacle is missing properties: {missing_properties}')

    route_markers = ROOT / 'world' / 'include' / 'showroom_routes.inc'
    marker_count = route_markers.read_text(encoding='utf-8').count('route_marker(')
    if marker_count > 350:
        raise ValueError(
            f'Too many Stage route markers for virtual GPUs: {marker_count}')

    pgm = ROOT / 'world' / 'maps' / 'showroom_final.pgm'
    with pgm.open('rb') as stream:
        header = stream.readline(), stream.readline(), stream.readline()
    if header != (b'P5\n', b'1000 700\n', b'255\n'):
        raise ValueError(f'Unexpected PGM header: {header!r}')

    generator = load_generator()
    raster = generator.build_map()
    generator.validate_routes(raster)

    if yaml is not None:
        graph = yaml.safe_load((
            ROOT / 'config' / 'navigation_graph.yaml').read_text(
                encoding='utf-8'))
        routes = yaml.safe_load((
            ROOT / 'config' / 'routes.yaml').read_text(
                encoding='utf-8'))['routes']
        labels = {}
        for route_name in graph['route_sources']:
            for waypoint in routes[route_name]['waypoints']:
                labels[waypoint['label']] = (
                    float(waypoint['x']), float(waypoint['y']))
        sample_angles = [2.0 * math.pi * i / 24.0 for i in range(24)]
        for connector in graph.get('connectors') or []:
            start = labels[connector['from']]
            goal = labels[connector['to']]
            for x, y in generator.interpolate(start, goal):
                samples = [(x, y)] + [
                    (
                        x + 0.44 * math.cos(angle),
                        y + 0.44 * math.sin(angle),
                    )
                    for angle in sample_angles
                ]
                if any(raster.occupied(sx, sy) for sx, sy in samples):
                    raise RuntimeError(
                        'Navigation connector clearance failed: '
                        f'{connector["from"]}->{connector["to"]}')

    print(f'Python syntax OK: {len(python_files)} files')
    yaml_mode = 'PyYAML parse' if yaml is not None else 'basic structure'
    print(f'YAML {yaml_mode} OK: {len(yaml_files)} files')
    print(f'Stage includes OK: {includes}')
    print(
        f'Stage odometry/update interval: {position_interval} ms '
        '(matches all worlds)')
    print('Stage odometry noise: zero (fixed map->odom profile)')
    print('Draggable laser-visible test obstacle: OK')
    print(f'Stage route marker count: {marker_count}')
    print('package.xml and 1000x700 PGM header: OK')
    print('Route clearance (generated route safety profile): OK')
    print('Navigation connector clearance (0.44 m): OK')


if __name__ == '__main__':
    main()
