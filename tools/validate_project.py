#!/usr/bin/env python3
"""Static validation for demo_stage assets; does not require a ROS installation."""

import ast
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

    world = ROOT / 'world' / 'showroom_final.world'
    world_text = world.read_text(encoding='utf-8')
    if world_text.count('(') != world_text.count(')'):
        raise ValueError('Unbalanced parentheses in showroom_final.world')
    if not re.search(r'^paused\s+0\s*$', world_text, re.MULTILINE):
        raise ValueError('Stage world must start unpaused for headless operation')
    if not re.search(r'^speedup\s+[0-9.]+\s*$', world_text, re.MULTILINE):
        raise ValueError('Stage world must declare an explicit GUI speedup')
    includes = re.findall(r'include\s+"([^"]+)"', world_text)
    missing = [name for name in includes if not (world.parent / name).is_file()]
    if missing:
        raise FileNotFoundError(f'Missing Stage includes: {missing}')

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
    generator.validate_routes(generator.build_map())

    print(f'Python syntax OK: {len(python_files)} files')
    yaml_mode = 'PyYAML parse' if yaml is not None else 'basic structure'
    print(f'YAML {yaml_mode} OK: {len(yaml_files)} files')
    print(f'Stage includes OK: {includes}')
    print('Draggable laser-visible test obstacle: OK')
    print(f'Stage route marker count: {marker_count}')
    print('package.xml and 1000x700 PGM header: OK')
    print('Route clearance (0.42 m): OK')


if __name__ == '__main__':
    main()
