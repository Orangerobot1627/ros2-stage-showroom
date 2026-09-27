#!/usr/bin/env python3
"""Generate the Stage occupancy bitmap, Nav2 map metadata, routes and preview."""

from __future__ import annotations

import math
from pathlib import Path
import struct
import zlib


RESOLUTION = 0.05
WIDTH_M = 50.0
HEIGHT_M = 35.0
WIDTH = int(WIDTH_M / RESOLUTION)
HEIGHT = int(HEIGHT_M / RESOLUTION)
X_MIN = -WIDTH_M / 2.0
Y_MIN = -HEIGHT_M / 2.0
FREE = 254
OCCUPIED = 0

ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = ROOT / 'world' / 'maps'
NAV_MAP_DIR = ROOT / 'map'
CONFIG_DIR = ROOT / 'config'
INCLUDE_DIR = ROOT / 'world' / 'include'


ROUTES = {
    'guide_history_blue': [
        (0.0, -14.5, 'entrance'),
        (0.0, -10.5, 'stairs_clearance'),
        (3.5, -8.0, 'coffee_south_east'),
        (6.0, -5.0, 'history_panel_1'),
        (7.0, -1.0, 'history_panel_2'),
        (7.0, 3.0, 'history_panel_3'),
        (4.5, 6.5, 'history_panel_4'),
        (0.0, 7.6, 'history_panel_5'),
        (-4.5, 6.5, 'history_panel_6'),
        (-7.0, 3.5, 'history_panel_7'),
        (-7.0, 0.0, 'history_panel_8'),
        (-7.0, -7.7, 'vision_hall_entry'),
    ],
    'vision_yellow': [
        (-7.0, -7.7, 'vision_hall_entry'),
        (-9.0, -7.7, 'vision_inside'),
        (-12.0, -6.0, 'vision_display_east'),
        (-18.5, -5.5, 'vision_display_north'),
        (-21.5, -7.5, 'vision_display_west'),
        (-21.0, -11.5, 'vision_display_south_west'),
        (-16.0, -12.0, 'vision_display_south'),
        (-11.0, -11.0, 'vision_display_south_east'),
        (-10.0, -8.0, 'vision_loop_close'),
        (-12.0, -5.0, 'vision_exit_approach'),
        (-15.0, -4.0, 'vision_semi_open_exit'),
        (-15.0, -2.3, 'vision_exit'),
    ],
    'robotics_yellow': [
        (-15.0, -2.3, 'to_robotics'),
        (-12.0, 2.5, 'robotics_entry_approach'),
        (-11.5, 4.5, 'robotics_entry'),
        (-11.0, 6.0, 'robotics_inside'),
        (-14.0, 6.0, 'robotics_display_south'),
        (-20.5, 6.2, 'robotics_display_south_west'),
        (-21.5, 11.0, 'robotics_display_west'),
        (-18.5, 14.0, 'robotics_display_north_west'),
        (-11.0, 14.0, 'robotics_display_north_east'),
        (-10.0, 10.5, 'robotics_display_east'),
        (-12.5, 8.5, 'robotics_loop_close'),
        (-10.0, 11.8, 'hidden_door_approach'),
        (-7.5, 12.0, 'hidden_door_entry'),
    ],
    'time_tunnel_red': [
        (-7.5, 12.0, 'hidden_door_entry'),
        (-5.0, 12.0, 'tunnel_entry'),
        (-3.3, 12.0, 'tunnel_turn_1'),
        (-3.3, 14.2, 'tunnel_turn_2'),
        (0.0, 14.2, 'tunnel_center_north'),
        (0.0, 11.0, 'tunnel_center_south'),
        (3.3, 11.0, 'tunnel_turn_3'),
        (3.3, 12.0, 'tunnel_turn_4'),
        (5.0, 12.0, 'tunnel_exit'),
        (7.5, 12.0, 'hidden_door_exit'),
    ],
    'dance_yellow': [
        (7.5, 12.0, 'dance_hall_entry'),
        (10.0, 12.0, 'dance_inside'),
        (11.5, 14.0, 'dance_display_north_west'),
        (19.0, 14.0, 'dance_display_north_east'),
        (21.5, 11.5, 'dance_display_east'),
        (21.0, 6.5, 'dance_display_south_east'),
        (18.0, 6.0, 'dance_display_south'),
        (13.0, 6.0, 'dance_display_south_west'),
        (10.0, 7.0, 'dance_display_west'),
        (9.5, 10.0, 'dance_loop_close'),
        (11.0, 12.0, 'dance_loop_end'),
        (14.5, 5.8, 'dance_exit_approach'),
        (14.5, 3.2, 'dance_semi_open_exit'),
    ],
    'lounge_yellow': [
        (14.5, 3.2, 'to_lounge'),
        (15.5, 1.8, 'lounge_top_entry'),
        (22.0, 0.5, 'lounge_work_area'),
        (23.0, -3.0, 'lounge_north_east'),
        (23.0, -8.8, 'lounge_south_east'),
        (19.0, -9.0, 'lounge_sofa_area'),
        (16.5, -8.5, 'lounge_center'),
        (12.0, -8.0, 'lounge_side_entry'),
        (12.0, -5.0, 'lounge_rest_area'),
        (15.0, -5.0, 'guide_destination'),
    ],
    'coffee_delivery_green': [
        (2.3, -14.5, 'coffee_robot_standby'),
        (2.3, -13.0, 'leave_standby'),
        (4.5, -11.5, 'enter_showroom'),
        (5.0, -10.0, 'coffee_route_south'),
        (5.0, -7.0, 'coffee_route_inner'),
        (3.5, -5.3, 'coffee_pickup_approach'),
        (0.0, -4.4, 'coffee_pickup'),
        (3.5, -5.3, 'coffee_departure'),
        (6.5, -7.0, 'coffee_route_east'),
        (9.8, -7.8, 'lounge_side_door'),
        (12.0, -8.0, 'lounge_delivery_approach'),
        (15.0, -8.5, 'lounge_delivery'),
        (12.0, -8.0, 'return_from_lounge'),
        (9.8, -7.8, 'leave_lounge'),
        (6.5, -7.0, 'return_east'),
        (5.0, -10.0, 'return_south'),
        (4.5, -11.5, 'return_to_entrance'),
        (2.3, -13.0, 'standby_approach'),
        (2.3, -14.5, 'coffee_robot_standby'),
    ],
}


def merge_routes(*names):
    merged = []
    for name in names:
        points = ROUTES[name]
        if merged and merged[-1][:2] == points[0][:2]:
            merged.extend(points[1:])
        else:
            merged.extend(points)
    return merged


ROUTES['guide_full_route'] = merge_routes(
    'guide_history_blue',
    'vision_yellow',
    'robotics_yellow',
    'time_tunnel_red',
    'dance_yellow',
    'lounge_yellow',
)
ROUTES['coffee_delivery_route'] = ROUTES['coffee_delivery_green']


class Raster:
    def __init__(self):
        self.data = bytearray([FREE]) * (WIDTH * HEIGHT)

    @staticmethod
    def world_to_pixel(x, y):
        px = int(round((x - X_MIN) / RESOLUTION))
        py = int(round((HEIGHT_M / 2.0 - y) / RESOLUTION))
        return px, py

    def set_pixel(self, px, py, value=OCCUPIED):
        if 0 <= px < WIDTH and 0 <= py < HEIGHT:
            self.data[py * WIDTH + px] = value

    def rect(self, x0, y0, x1, y1, value=OCCUPIED):
        left, top = self.world_to_pixel(min(x0, x1), max(y0, y1))
        right, bottom = self.world_to_pixel(max(x0, x1), min(y0, y1))
        left, right = max(0, left), min(WIDTH - 1, right)
        top, bottom = max(0, top), min(HEIGHT - 1, bottom)
        row = bytes([value]) * (right - left + 1)
        for py in range(top, bottom + 1):
            start = py * WIDTH + left
            self.data[start:start + len(row)] = row

    def circle(self, cx, cy, radius, value=OCCUPIED):
        px0, py0 = self.world_to_pixel(cx, cy)
        radius_px = int(math.ceil(radius / RESOLUTION))
        limit = radius_px * radius_px
        for dy in range(-radius_px, radius_px + 1):
            span = int(math.sqrt(max(0, limit - dy * dy)))
            for dx in range(-span, span + 1):
                self.set_pixel(px0 + dx, py0 + dy, value)

    def rotated_rect(self, cx, cy, length, width, degrees, value=OCCUPIED):
        angle = math.radians(degrees)
        ca, sa = math.cos(angle), math.sin(angle)
        radius = 0.5 * math.hypot(length, width)
        px0, py0 = self.world_to_pixel(cx - radius, cy + radius)
        px1, py1 = self.world_to_pixel(cx + radius, cy - radius)
        for py in range(max(0, py0), min(HEIGHT - 1, py1) + 1):
            y = HEIGHT_M / 2.0 - py * RESOLUTION
            for px in range(max(0, px0), min(WIDTH - 1, px1) + 1):
                x = X_MIN + px * RESOLUTION
                dx, dy = x - cx, y - cy
                local_x = ca * dx + sa * dy
                local_y = -sa * dx + ca * dy
                if abs(local_x) <= length / 2.0 and abs(local_y) <= width / 2.0:
                    self.set_pixel(px, py, value)

    def occupied(self, x, y):
        px, py = self.world_to_pixel(x, y)
        if not (0 <= px < WIDTH and 0 <= py < HEIGHT):
            return True
        return self.data[py * WIDTH + px] < 128


def wall_h(raster, y, x0, x1, thickness=0.30):
    raster.rect(x0, y - thickness / 2.0, x1, y + thickness / 2.0)


def wall_v(raster, x, y0, y1, thickness=0.30):
    raster.rect(x - thickness / 2.0, y0, x + thickness / 2.0, y1)


def build_map():
    r = Raster()

    # Outer shell and entrance corridor.
    wall_h(r, 16.8, -24.7, 24.7, 0.35)
    wall_v(r, -24.7, -16.8, 16.8, 0.35)
    wall_v(r, 24.7, -16.8, 16.8, 0.35)
    wall_h(r, -16.8, -24.7, -3.5, 0.35)
    wall_h(r, -16.8, 3.5, 24.7, 0.35)
    wall_v(r, -3.5, -16.8, -13.8, 0.25)
    wall_v(r, 3.5, -16.8, -13.8, 0.25)
    wall_h(r, -13.8, -24.7, -3.5, 0.30)
    wall_h(r, -13.8, 3.5, 24.7, 0.30)

    # Vision hall: semi-open entrance on the right and exit on the top.
    wall_h(r, -3.2, -24.7, -17.0)
    wall_h(r, -3.2, -13.2, -8.0)
    wall_v(r, -8.0, -13.8, -9.0)
    wall_v(r, -8.0, -6.5, -3.2)

    # Robotics hall and its hidden-door approach.
    wall_h(r, 3.5, -24.7, -13.2)
    wall_h(r, 3.5, -10.0, -8.0)
    wall_v(r, -8.0, 3.5, 10.8)
    wall_v(r, -8.0, 13.2, 16.8)

    # Enclosed time tunnel with two side openings and two baffles.
    wall_h(r, 9.0, -6.0, 6.0)
    wall_v(r, -6.0, 9.0, 10.8)
    wall_v(r, -6.0, 13.2, 16.8)
    wall_v(r, 6.0, 9.0, 10.8)
    wall_v(r, 6.0, 13.2, 16.8)
    wall_v(r, -2.0, 9.0, 13.0, 0.25)
    wall_v(r, 2.0, 13.0, 16.8, 0.25)

    # Dance hall: hidden-door entrance on the left, semi-open exit below.
    wall_h(r, 3.5, 8.0, 12.0)
    wall_h(r, 3.5, 15.0, 24.7)
    wall_v(r, 8.0, 3.5, 10.8)
    wall_v(r, 8.0, 13.2, 16.8)

    # Lounge: top opening and wide side passage for the coffee robot.
    wall_h(r, 2.5, 9.0, 14.0)
    wall_h(r, 2.5, 17.0, 24.7)
    wall_v(r, 9.0, -13.8, -9.2)
    wall_v(r, 9.0, -6.3, 2.5)

    # Main landmarks and exhibition islands.
    r.circle(0.0, 0.0, 3.60)          # coffee bar
    r.circle(-16.0, -8.5, 1.40)       # vision globe
    r.circle(-16.0, 9.5, 1.70)        # robotics display
    r.circle(16.0, 9.5, 2.35)         # dance stage

    # Technology-history panels around the coffee bar.
    for cx, cy, angle in [
        (0.0, 5.15, 0), (3.65, 3.65, 45), (5.15, 0.0, 90),
        (3.65, -3.65, 135), (0.0, -5.15, 0),
        (-3.65, -3.65, 45), (-5.15, 0.0, 90), (-3.65, 3.65, 135),
    ]:
        r.rotated_rect(cx, cy, 1.30, 0.22, angle)

    # Hall displays/panels, deliberately kept close to walls.
    for args in [
        (-21.5, -5.2, 2.5, 0.35, 90), (-19.0, -12.5, 3.0, 0.35, 0),
        (-12.5, -12.5, 2.8, 0.35, 0), (-10.0, -5.0, 2.3, 0.35, 90),
        (-22.0, 7.0, 2.2, 0.35, 90), (-20.0, 14.8, 3.0, 0.35, 0),
        (-12.0, 14.8, 2.8, 0.35, 0), (-10.0, 7.0, 2.0, 0.35, 90),
        (10.0, 14.8, 2.3, 0.35, 0), (19.5, 14.8, 3.0, 0.35, 0),
        (22.5, 8.0, 2.6, 0.35, 90), (18.5, 4.5, 2.8, 0.35, 0),
    ]:
        r.rotated_rect(*args)

    # Lounge furniture and work tables.
    r.rect(18.0, -1.8, 20.8, -0.8)
    r.rect(20.8, -6.0, 22.2, -3.5)
    r.rect(17.5, -11.5, 20.5, -10.4)
    r.rect(12.0, -12.5, 15.0, -11.6)
    r.rect(13.5, -7.0, 15.5, -6.2)
    r.circle(14.5, -2.0, 0.55)

    # Plants/columns provide natural separation and useful LiDAR features.
    for x, y in [
        (-7.2, -12.8), (-6.0, 2.5), (-7.0, 7.5), (-7.0, 15.0),
        (7.0, 15.0), (7.0, 7.0), (8.0, -12.5), (8.0, -2.5),
        (-22.5, -1.0), (-22.5, 1.5),
        (-5.5, -7.5), (7.0, -12.0), (-5.5, 7.5), (5.5, 7.5),
    ]:
        r.circle(x, y, 0.35)

    return r


def write_pgm(raster, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as stream:
        stream.write(f'P5\n{WIDTH} {HEIGHT}\n255\n'.encode('ascii'))
        stream.write(raster.data)


def png_chunk(kind, payload):
    return (
        struct.pack('>I', len(payload))
        + kind
        + payload
        + struct.pack('>I', zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def draw_preview(raster, path):
    pixels = bytearray(WIDTH * HEIGHT * 3)
    for index, value in enumerate(raster.data):
        color = (245, 247, 250) if value > 127 else (28, 35, 45)
        offset = index * 3
        pixels[offset:offset + 3] = bytes(color)

    colors = {
        'guide_history_blue': (20, 140, 255),
        'vision_yellow': (255, 210, 0),
        'robotics_yellow': (255, 210, 0),
        'time_tunnel_red': (255, 60, 45),
        'dance_yellow': (255, 210, 0),
        'lounge_yellow': (255, 210, 0),
        'coffee_delivery_green': (0, 220, 105),
    }

    def dot(px, py, radius, color):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    x, y = px + dx, py + dy
                    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                        offset = (y * WIDTH + x) * 3
                        pixels[offset:offset + 3] = bytes(color)

    def line(a, b, color):
        x0, y0 = Raster.world_to_pixel(a[0], a[1])
        x1, y1 = Raster.world_to_pixel(b[0], b[1])
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for step in range(steps + 1):
            t = step / steps
            dot(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), 3, color)

    for name, color in colors.items():
        points = ROUTES[name]
        for a, b in zip(points, points[1:]):
            line(a, b, color)
        for point in points:
            px, py = Raster.world_to_pixel(point[0], point[1])
            dot(px, py, 5, color)

    raw = b''.join(
        b'\x00' + bytes(pixels[row * WIDTH * 3:(row + 1) * WIDTH * 3])
        for row in range(HEIGHT)
    )
    png = b'\x89PNG\r\n\x1a\n'
    png += png_chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 2, 0, 0, 0))
    png += png_chunk(b'IDAT', zlib.compress(raw, 9))
    png += png_chunk(b'IEND', b'')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def write_nav_map_metadata(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'image: ../world/maps/showroom_final.pgm\n'
        'mode: trinary\n'
        f'resolution: {RESOLUTION:.2f}\n'
        f'origin: [{X_MIN:.1f}, {Y_MIN:.1f}, 0.0]\n'
        'negate: 0\n'
        'occupied_thresh: 0.65\n'
        'free_thresh: 0.25\n',
        encoding='utf-8',
    )


def write_routes(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    exported = [
        'guide_history_blue', 'vision_yellow', 'robotics_yellow',
        'time_tunnel_red', 'dance_yellow', 'lounge_yellow',
        'guide_full_route', 'coffee_delivery_route',
    ]
    lines = [
        '# Generated by tools/generate_showroom_assets.py',
        'frame_id: world',
        'routes:',
    ]
    for name in exported:
        lines.extend([
            f'  {name}:',
            '    loop: false',
            '    waypoints:',
        ])
        for x, y, label in ROUTES[name]:
            lines.append(f'      - {{x: {x:.2f}, y: {y:.2f}, label: {label}}}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def interpolate(a, b, spacing=0.20):
    distance = math.hypot(b[0] - a[0], b[1] - a[1])
    steps = max(1, int(math.ceil(distance / spacing)))
    for index in range(steps + 1):
        t = index / steps
        yield a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def validate_routes(raster, clearance=0.42):
    failures = []
    checks = ['guide_full_route', 'coffee_delivery_route']
    sample_angles = [2.0 * math.pi * i / 24.0 for i in range(24)]
    for name in checks:
        points = ROUTES[name]
        for segment_index, (a, b) in enumerate(zip(points, points[1:])):
            for x, y in interpolate(a, b):
                samples = [(x, y)] + [
                    (x + clearance * math.cos(angle), y + clearance * math.sin(angle))
                    for angle in sample_angles
                ]
                if any(raster.occupied(sx, sy) for sx, sy in samples):
                    failures.append((name, segment_index, round(x, 2), round(y, 2)))
                    break
    if failures:
        preview = ', '.join(str(item) for item in failures[:12])
        raise RuntimeError(f'Route clearance validation failed: {preview}')


def write_stage_route_markers(path):
    colors = {
        'guide_history_blue': 'DodgerBlue',
        'vision_yellow': 'Gold',
        'robotics_yellow': 'Gold',
        'time_tunnel_red': 'Red',
        'dance_yellow': 'Gold',
        'lounge_yellow': 'Gold',
        'coffee_delivery_green': 'LimeGreen',
    }
    lines = [
        '# Generated by tools/generate_showroom_assets.py',
        'define route_marker model',
        '(',
        '  size [ 0.16 0.16 0.01 ]',
        '  gui_nose 0',
        '  gui_outline 0',
        '  obstacle_return 0',
        '  ranger_return -1',
        ')',
        '',
    ]
    marker_id = 0
    for name, color in colors.items():
        points = ROUTES[name]
        for a, b in zip(points, points[1:]):
            # Dense marker models overload VMware's virtual OpenGL driver.
            # The route YAML and preview retain full detail; Stage only needs
            # a lightweight visual guide.
            for x, y in interpolate(a, b, spacing=2.0):
                marker = (
                    f'route_marker( name "route_{marker_id}" '
                    f'pose [ {x:.2f} {y:.2f} 0.01 0 ] color "{color}" )'
                )
                lines.append(marker)
                marker_id += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    raster = build_map()
    validate_routes(raster)
    write_pgm(raster, MAP_DIR / 'showroom_final.pgm')
    draw_preview(raster, MAP_DIR / 'showroom_preview.png')
    write_nav_map_metadata(NAV_MAP_DIR / 'showroom_final.yaml')
    write_routes(CONFIG_DIR / 'routes.yaml')
    write_stage_route_markers(INCLUDE_DIR / 'showroom_routes.inc')
    print(f'Generated {WIDTH}x{HEIGHT} map at {RESOLUTION:.2f} m/cell')
    print('Validated guide_full_route and coffee_delivery_route with 0.42 m clearance')


if __name__ == '__main__':
    main()
