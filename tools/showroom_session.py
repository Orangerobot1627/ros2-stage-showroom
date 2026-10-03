#!/usr/bin/env python3
"""Start and inspect isolated demo_stage simulation sessions."""

import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time


DOMAIN_POOL = tuple(range(81, 100))
DISCOVERY_RANGE = 'LOCALHOST'
ANSI_ESCAPE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')

NAVIGATION_NAMES = {
    'WAITING': '等待任务', 'NAVIGATING': '正在导航',
    'BLOCKED': '遇障停车', 'PAUSED': '业务暂停',
    'COMPLETED': '任务完成', 'CANCELLED': '任务取消',
    'AVOIDING': '正在局部绕障',
}
GUIDE_STATE_NAMES = {
    'IDLE': '空闲', 'RECEPTION': '入口接待', 'TOURING': '导览中',
    'GOING_TO_LOUNGE': '前往休息区', 'AT_LOUNGE': '已到休息区',
    'PAUSED': '已暂停', 'BLOCKED': '遇障等待',
    'COMPLETED': '导览完成', 'CANCELLED': '已取消',
}
COFFEE_STATE_NAMES = {
    'STANDBY': '待命', 'TO_PICKUP': '前往取咖啡',
    'PICKUP': '正在取咖啡', 'DELIVERING': '配送中',
    'DELIVERED': '已送达', 'RETURNING': '返回待机点',
    'RETURNED': '已返回', 'PAUSED': '已暂停', 'BLOCKED': '遇障等待',
    'CANCELLED': '已取消',
}


def chinese_waypoint(label):
    """Return a compact Chinese description for a route label."""
    if not label:
        return '尚未到达第一个航点'
    exact = {
        'entrance': '入口接待点',
        'stairs_clearance': '入口通道',
        'coffee_south_east': '咖啡区东南侧',
        'vision_hall_entry': '视觉展厅入口',
        'vision_inside': '视觉展厅内部',
        'vision_loop_close': '视觉展厅环线汇合点',
        'vision_exit_approach': '视觉展厅出口前',
        'vision_semi_open_exit': '视觉展厅半开放出口',
        'vision_exit': '视觉展厅出口',
        'to_robotics': '前往机器人展厅',
        'robotics_entry_approach': '机器人展厅入口前',
        'robotics_entry': '机器人展厅入口',
        'robotics_inside': '机器人展厅内部',
        'robotics_loop_close': '机器人展厅环线汇合点',
        'hidden_door_approach': '隐藏通道入口前',
        'hidden_door_entry': '隐藏通道入口',
        'tunnel_entry': '时空隧道入口',
        'tunnel_center_north': '时空隧道北段',
        'tunnel_center_south': '时空隧道南段',
        'tunnel_exit': '时空隧道出口',
        'hidden_door_exit': '隐藏通道出口',
        'dance_hall_entry': '科技舞蹈展厅入口',
        'dance_inside': '科技舞蹈展厅内部',
        'dance_loop_close': '科技舞蹈展厅环线汇合点',
        'dance_loop_end': '科技舞蹈展厅环线终点',
        'dance_exit_approach': '科技舞蹈展厅出口前',
        'dance_semi_open_exit': '科技舞蹈展厅半开放出口',
        'to_lounge': '前往休息区',
        'lounge_top_entry': '休息区北入口',
        'lounge_work_area': '休息区工作台',
        'lounge_sofa_area': '休息区沙发区',
        'lounge_center': '休息区中央',
        'lounge_side_entry': '休息区侧入口',
        'lounge_rest_area': '休息区服务点',
        'guide_destination': '导览终点',
        'coffee_robot_standby': '咖啡机器人待机点',
        'leave_standby': '离开待机点',
        'enter_showroom': '进入展馆',
        'coffee_route_south': '咖啡配送南通道',
        'coffee_route_inner': '咖啡配送内通道',
        'coffee_pickup_approach': '咖啡取货点前',
        'coffee_pickup': '咖啡取货点',
        'coffee_departure': '咖啡区出发点',
        'coffee_route_east': '咖啡配送东通道',
        'lounge_side_door': '休息区侧门',
        'lounge_delivery_approach': '休息区交付点前',
        'lounge_delivery': '咖啡交付点',
        'return_from_lounge': '离开休息区',
        'leave_lounge': '返回通道入口',
        'return_east': '返回东通道',
        'return_south': '返回南通道',
        'return_to_entrance': '返回入口区',
        'standby_approach': '待机点前',
    }
    if label in exact:
        return exact[label]
    panel = re.fullmatch(r'history_panel_(\d+)', label)
    if panel:
        return f'科技历史展板 {panel.group(1)}'
    turn = re.fullmatch(r'tunnel_turn_(\d+)', label)
    if turn:
        return f'时空隧道转角 {turn.group(1)}'
    prefixes = {
        'vision_display_': '视觉展厅展位',
        'robotics_display_': '机器人展厅展位',
        'dance_display_': '科技舞蹈展厅展位',
        'lounge_': '休息区',
    }
    for prefix, name in prefixes.items():
        if label.startswith(prefix):
            return f'{name}（{label.removeprefix(prefix)}）'
    return label


def format_duration(value):
    """Format seconds with millisecond precision."""
    if not isinstance(value, (int, float)):
        return '无数据'
    total_milliseconds = int(round(max(0.0, float(value)) * 1000.0))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    total_minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(total_minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}'


def render_robot_summary(name, robot):
    """Render one robot from a monitor document."""
    navigation = NAVIGATION_NAMES.get(
        robot.get('navigation_state'), robot.get('navigation_state', '未知'))
    waypoint = chinese_waypoint(robot.get('current_waypoint'))
    pose = robot.get('pose') or {}
    velocity = robot.get('command_velocity') or {}
    clearance = robot.get('front_clearance_m')
    clearance_text = '无数据' if clearance is None else f'{clearance:.2f} m'
    lines = [
        f'{name}: {navigation}  |  航点 '
        f'{robot.get("waypoint_index", 0)}/{robot.get("waypoint_total", 0)}  '
        f'|  {waypoint}',
        '  位置: '
        f'x={pose.get("x", 0.0):.2f}, y={pose.get("y", 0.0):.2f}, '
        f'朝向={pose.get("yaw_deg", 0.0):.1f}°  |  '
        f'任务时间 {format_duration(robot.get("mission_elapsed_sec"))}',
        '  指令速度: '
        f'{velocity.get("linear_x", 0.0):.2f} m/s, '
        f'{velocity.get("angular_z", 0.0):.2f} rad/s  |  '
        f'前方净空 {clearance_text}',
    ]
    nav2_feedback = robot.get('nav2_feedback') or {}
    remaining = nav2_feedback.get('distance_remaining_m')
    eta = nav2_feedback.get('estimated_time_remaining_sec')
    if isinstance(remaining, (int, float)):
        eta_text = format_duration(eta)
        feedback_age = nav2_feedback.get('feedback_age_sec')
        age_text = (
            f'{feedback_age:.1f}s 前更新'
            if isinstance(feedback_age, (int, float)) else '更新时间未知')
        lines.append(
            f'  Nav2进度: 距当前目标 {remaining:.2f} m  |  '
            f'预计 {eta_text}  |  '
            f'恢复 {nav2_feedback.get("number_of_recoveries", 0)} 次  |  '
            f'{age_text}')
    if robot.get('navigation_state') == 'AVOIDING':
        local = robot.get('local_planner') or {}
        lines.append(
            '  局部导航: 正在自动绕过障碍  |  '
            f'阶段 {local.get("state", "未知")}  |  '
            f'累计绕障 {local.get("avoidance_count", 0)} 次')
    elif robot.get('navigation_state') == 'BLOCKED':
        lines.append(
            '  障碍恢复: 已停车，障碍移开后自动继续  |  '
            f'已等待 {format_duration(robot.get("blocked_duration_sec"))}')
    elif robot.get('recovery_state') == 'RESUMED_AFTER_CLEARANCE':
        lines.append(
            '  障碍恢复: 障碍已清除，导航已继续  |  '
            f'上次阻塞 '
            f'{format_duration(robot.get("last_blocked_duration_sec"))}  |  '
            f'累计 {robot.get("block_count", 0)} 次')
    else:
        lines.append(
            f'  障碍恢复: 正常  |  累计阻塞 '
            f'{robot.get("block_count", 0)} 次')
    return lines


def render_monitor(document, state):
    """Render a compact Chinese terminal dashboard."""
    business = document.get('business') or {}
    robots = document.get('robots') or {}
    trigger_status = (
        '已到达' if business.get('coffee_trigger_reached') else '未到达')
    overrides = business.get('human_overrides') or {}
    override_parts = []
    for robot_id, override in overrides.items():
        robot_name = {
            'robot_0': '蓝色',
            'robot_1': '绿色',
        }.get(robot_id, robot_id)
        override_parts.append(
            f'{robot_name}:{override.get("action", "未知")} '
            f'{override.get("remaining_sec", 0.0):.1f}s')
    override_text = '、'.join(override_parts) if override_parts else '无'
    plan = business.get('active_plan') or {}
    plan_state = plan.get('state', 'IDLE')
    plan_id = plan.get('plan_id') or '无'
    current_step = plan.get('current_step')
    step_total = plan.get('step_total', 0)
    if plan_state == 'IDLE':
        step_text = '无'
    elif current_step is None and plan_state == 'SUCCEEDED':
        step_text = '完成'
    else:
        step_text = f'{(current_step or 0) + 1}/{step_total}'
    lines = [
        '科技展馆双机器人运行监控',
        f'会话 {state["session_id"]}  |  Domain {state["domain_id"]}  |  '
        f'仿真时间 {format_duration(document.get("sim_time_sec"))}',
        f'数据序号 {document.get("sequence", 0)}  |  '
        f'生成时间 {document.get("published_at", "无数据")}',
        '',
        '业务: '
        f'导览={GUIDE_STATE_NAMES.get(business.get("guide_state"), "未知")}  '
        f'咖啡={COFFEE_STATE_NAMES.get(business.get("coffee_state"), "未知")}  '
        f'配送触发点={chinese_waypoint(business.get("coffee_trigger"))}'
        f'（{trigger_status}）',
        f'多任务计划: {plan_id}  状态={plan_state}  步骤={step_text}  |  '
        f'配送目标={business.get("coffee_target") or "无"}  '
        f'饮料={business.get("beverage") or "无"}',
        f'人工临时接管: {override_text}',
        '',
    ]
    lines.extend(render_robot_summary(
        '蓝色导览机器人', robots.get('robot_0') or {}))
    lines.append('')
    lines.extend(render_robot_summary(
        '绿色服务机器人', robots.get('robot_1') or {}))
    lines.extend(['', '按 Ctrl+C 退出监控，不会停止仿真。'])
    return '\n'.join(lines)


class SessionError(RuntimeError):
    """An actionable session-management error."""


def runtime_dir():
    bases = []
    configured_runtime = os.environ.get('XDG_RUNTIME_DIR')
    if configured_runtime:
        bases.append(Path(configured_runtime))
    bases.append(Path(tempfile.gettempdir()))
    for base in bases:
        path = base / f'demo_stage-{os.getuid()}'
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            if path.is_symlink() or path.stat().st_uid != os.getuid():
                continue
            path.chmod(0o700)
            return path
        except OSError:
            continue
    raise SessionError('无法创建仅限当前用户访问的会话状态目录。')


def atomic_write_json(path, document):
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    os.replace(temporary, path)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def process_start_ticks(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text(
            encoding='utf-8').split()
        return int(fields[21])
    except (FileNotFoundError, IndexError, OSError, ValueError):
        return None


def process_matches(state):
    pid = state.get('child_pid')
    start_ticks = state.get('child_start_ticks')
    if not isinstance(pid, int) or not isinstance(start_ticks, int):
        return False
    return process_start_ticks(pid) == start_ticks


def discovery_environment(domain):
    log_directory = runtime_dir() / 'ros-logs'
    log_directory.mkdir(mode=0o700, exist_ok=True)
    environment = os.environ.copy()
    environment['ROS_DOMAIN_ID'] = str(domain)
    environment['ROS_AUTOMATIC_DISCOVERY_RANGE'] = DISCOVERY_RANGE
    environment['ROS_LOG_DIR'] = str(log_directory)
    return environment


def visible_nodes(domain):
    command = [
        'ros2', 'node', 'list', '--no-daemon', '--spin-time', '0.8',
    ]
    try:
        result = subprocess.run(
            command,
            env=discovery_environment(domain),
            text=True,
            capture_output=True,
            timeout=5.0,
            check=False,
        )
    except subprocess.TimeoutExpired as exception:
        raise SessionError(
            f'检查 ROS Domain {domain} 时超时；没有在未知状态下启动仿真。'
        ) from exception

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SessionError(
            f'无法检查 ROS Domain {domain}: {detail or "ros2 返回错误"}')
    cleaned_output = ANSI_ESCAPE.sub('', result.stdout)
    lines = [line.strip() for line in cleaned_output.splitlines()
             if line.strip()]
    diagnostics = [line for line in lines if not line.startswith('/')]
    error_words = (' error]', 'failed', 'failure', 'not permitted')
    if any(word in line.lower()
           for line in diagnostics for word in error_words):
        detail = '; '.join(diagnostics[:3])
        raise SessionError(
            f'ROS Domain {domain} 探测进程无法正常通信：{detail}')
    return [line for line in lines if line.startswith('/')]


def open_domain_lock(directory, domain):
    lock = (directory / f'domain-{domain}.lock').open('a+', encoding='utf-8')
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def allocate_domain(requested=None):
    directory = runtime_dir()
    allocator_path = directory / 'allocator.lock'
    with allocator_path.open('a+', encoding='utf-8') as allocator:
        fcntl.flock(allocator.fileno(), fcntl.LOCK_EX)

        if requested is not None:
            candidates = (requested,)
        else:
            cursor_path = directory / 'next-domain'
            try:
                next_domain = int(cursor_path.read_text().strip())
            except (FileNotFoundError, OSError, ValueError):
                next_domain = DOMAIN_POOL[0]
            start = (next_domain - DOMAIN_POOL[0]) % len(DOMAIN_POOL)
            candidates = DOMAIN_POOL[start:] + DOMAIN_POOL[:start]

        occupied = []
        for domain in candidates:
            lock = open_domain_lock(directory, domain)
            if lock is None:
                occupied.append(f'{domain}(由会话管理器锁定)')
                continue

            try:
                nodes = visible_nodes(domain)
            except Exception:
                lock.close()
                raise
            if nodes:
                occupied.append(f'{domain}(发现 {", ".join(nodes[:3])})')
                lock.close()
                continue

            if requested is None:
                next_index = (DOMAIN_POOL.index(domain) + 1) % len(DOMAIN_POOL)
                (directory / 'next-domain').write_text(
                    f'{DOMAIN_POOL[next_index]}\n', encoding='utf-8')
            return domain, lock

    if requested is not None:
        detail = occupied[0] if occupied else str(requested)
        raise SessionError(f'指定的 ROS Domain 已占用：{detail}')
    raise SessionError(
        '自动 Domain 池 81..99 已全部占用：' + '; '.join(occupied))


def validate_domain(value):
    domain = int(value)
    if not 0 <= domain <= 232:
        raise argparse.ArgumentTypeError('Domain 必须在 0..232 之间')
    return domain


def session_state_path(session_id):
    return runtime_dir() / f'session-{session_id}.json'


def current_state():
    current_path = runtime_dir() / 'current.json'
    state = read_json(current_path)
    if state and process_matches(state):
        return state
    states = active_states()
    if not states:
        current_path.unlink(missing_ok=True)
        return None
    state = max(states, key=lambda item: item.get('started_at', ''))
    atomic_write_json(current_path, state)
    return state


def remove_own_state(state):
    session_state_path(state['session_id']).unlink(missing_ok=True)
    current_path = runtime_dir() / 'current.json'
    current = read_json(current_path)
    if current and current.get('session_id') == state['session_id']:
        current_path.unlink(missing_ok=True)
        remaining = active_states()
        if remaining:
            latest = max(
                remaining, key=lambda item: item.get('started_at', ''))
            atomic_write_json(current_path, latest)


def send_group_signal(state, signum):
    if not process_matches(state):
        return False
    try:
        os.killpg(state['process_group'], signum)
        return True
    except ProcessLookupError:
        return False


def stop_process_group(state, interrupt_timeout=10.0):
    if not send_group_signal(state, signal.SIGINT):
        return

    deadline = time.monotonic() + interrupt_timeout
    while process_matches(state) and time.monotonic() < deadline:
        time.sleep(0.1)
    if process_matches(state):
        send_group_signal(state, signal.SIGTERM)

    deadline = time.monotonic() + 3.0
    while process_matches(state) and time.monotonic() < deadline:
        time.sleep(0.1)
    if process_matches(state):
        send_group_signal(state, signal.SIGKILL)


def open_monitor_terminals(domain, session_id, parent_pid):
    """Open Chinese and detailed subscribers before launching simulation."""
    terminal = shutil.which('gnome-terminal')
    if terminal is None:
        raise SessionError(
            '找不到 gnome-terminal，无法自动打开监控窗口。')
    environment = discovery_environment(domain)
    common = [
        '--domain', str(domain),
        '--session-id', session_id,
        '--parent-pid', str(parent_pid),
    ]
    specifications = (
        ('展馆中文监控', 'monitor', []),
        ('展馆详细监控', 'detail-monitor', ['--interval', '0.2']),
    )
    processes = []
    for title, action, extra in specifications:
        command = [
            terminal,
            '--wait',
            f'--title={title}',
            '--',
            'ros2', 'run', 'demo_stage', 'showroom_session', action,
            *common, *extra,
        ]
        process = subprocess.Popen(command, env=environment)
        processes.append(process)
    time.sleep(0.4)
    failed = [process.returncode for process in processes
              if process.poll() is not None]
    if failed:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        raise SessionError(
            f'监控窗口启动失败，终端返回码：{failed}')
    return processes


def apply_voice_launch_arguments(launch_arguments, enabled, rms_threshold):
    """Expand the concise voice option into launch arguments."""
    launch_arguments = list(launch_arguments)
    if enabled:
        requested = {
            item.split(':=', 1)[0]: item
            for item in launch_arguments if ':=' in item
        }
        for name in ('enable_llm', 'enable_voice'):
            value = requested.get(name)
            if value is not None and value.lower() != f'{name}:=true':
                raise SessionError(
                    f'--voice 与显式参数 {value} 冲突。')
            if value is None:
                launch_arguments.append(f'{name}:=true')
        explicit_threshold = any(
            item.startswith('voice_rms_threshold:=')
            for item in launch_arguments)
        if rms_threshold is not None:
            launch_arguments = [
                item for item in launch_arguments
                if not item.startswith('voice_rms_threshold:=')
            ]
            launch_arguments.append(
                'voice_rms_threshold:='
                f'{rms_threshold}')
        elif not explicit_threshold:
            launch_arguments.append('voice_rms_threshold:=150.0')
    return launch_arguments


def start_session(arguments):
    if shutil.which('ros2') is None:
        raise SessionError(
            '找不到 ros2；请先 source /opt/ros/jazzy/setup.bash 和工作区 '
            'install/setup.bash。')

    launch_arguments = list(arguments.launch_arguments)
    if launch_arguments[:1] == ['--']:
        launch_arguments.pop(0)
    launch_arguments = apply_voice_launch_arguments(
        launch_arguments, arguments.voice, arguments.voice_rms_threshold)
    if any(item.startswith('ros_domain_id:=') for item in launch_arguments):
        raise SessionError(
            '请使用 --domain 指定频道，不要在 launch 参数中重复设置 '
            'ros_domain_id。')

    domain, domain_lock = allocate_domain(arguments.domain)
    session_id = (
        dt.datetime.now().strftime('%Y%m%d-%H%M%S')
        + '-' + secrets.token_hex(2)
    )
    command = [
        'ros2', 'launch', 'demo_stage', arguments.launch_file,
        f'ros_domain_id:={domain}', *launch_arguments,
    ]
    environment = discovery_environment(domain)
    monitor_terminals = []

    print(f'[session] id: {session_id}', flush=True)
    print(f'[session] ROS_DOMAIN_ID: {domain}', flush=True)
    print(f'[session] discovery: {DISCOVERY_RANGE}', flush=True)
    print(
        '[session] 新终端接入：'
        'eval "$(ros2 run demo_stage showroom_session env)"',
        flush=True,
    )
    child = None
    state = None
    forwarded_signals = 0
    shutdown_started = None

    def forward_signal(signum, _frame):
        nonlocal forwarded_signals, shutdown_started
        if child is None or child.poll() is not None:
            return
        if shutdown_started is None:
            shutdown_started = time.monotonic()
        if signum == signal.SIGTERM:
            forwarded_signals = max(forwarded_signals, 2)
        else:
            forwarded_signals += 1
        if forwarded_signals == 2:
            forwarded = signal.SIGTERM
        elif forwarded_signals >= 3:
            forwarded = signal.SIGKILL
        else:
            forwarded = signal.SIGINT
        try:
            os.killpg(child.pid, forwarded)
        except ProcessLookupError:
            pass

    previous_sigint = signal.signal(signal.SIGINT, forward_signal)
    previous_sigterm = signal.signal(signal.SIGTERM, forward_signal)
    try:
        if arguments.monitor_windows:
            print('[session] 先启动中文监控和详细监控窗口...', flush=True)
            monitor_terminals = open_monitor_terminals(
                domain, session_id, os.getpid())
            time.sleep(arguments.monitor_lead_sec)

        child = subprocess.Popen(
            command,
            env=environment,
            start_new_session=True,
        )
        start_ticks = process_start_ticks(child.pid)
        if start_ticks is None:
            raise SessionError('启动 ros2 launch 后无法读取其进程状态。')

        state = {
            'session_id': session_id,
            'domain_id': domain,
            'discovery_range': DISCOVERY_RANGE,
            'manager_pid': os.getpid(),
            'child_pid': child.pid,
            'child_start_ticks': start_ticks,
            'process_group': child.pid,
            'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'command': command,
        }
        atomic_write_json(session_state_path(session_id), state)
        atomic_write_json(runtime_dir() / 'current.json', state)
        while True:
            try:
                return_code = child.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if shutdown_started is None:
                    continue
                elapsed = time.monotonic() - shutdown_started
                if elapsed >= 10.0 and forwarded_signals < 2:
                    forwarded_signals = 2
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                if elapsed >= 13.0 and forwarded_signals < 3:
                    forwarded_signals = 3
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        if forwarded_signals:
            return 0
        return return_code
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        if state is not None:
            if child is not None and child.poll() is None:
                stop_process_group(state)
            remove_own_state(state)
        for terminal in monitor_terminals:
            try:
                terminal.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                terminal.terminate()
        domain_lock.close()


def active_states():
    states = []
    for path in sorted(runtime_dir().glob('session-*.json')):
        state = read_json(path)
        if state and process_matches(state):
            states.append(state)
        else:
            path.unlink(missing_ok=True)
    return states


def show_status(_arguments):
    states = active_states()
    if not states:
        print('当前没有由 showroom_session 启动的活动仿真。')
        return 1
    for state in states:
        print(
            f'{state["session_id"]}: active, '
            f'Domain={state["domain_id"]}, PID={state["child_pid"]}')
    return 0


def show_business_status(arguments):
    state = current_state()
    if state is None:
        raise SessionError('没有可接入的当前仿真会话。')

    environment = discovery_environment(state['domain_id'])
    for name in ('ROS_DOMAIN_ID', 'ROS_AUTOMATIC_DISCOVERY_RANGE',
                 'ROS_LOG_DIR'):
        os.environ[name] = environment[name]

    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String

    received = []
    node = None
    rclpy.init(args=[])
    try:
        node = rclpy.create_node(f'showroom_status_cli_{os.getpid()}')
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        node.create_subscription(
            String,
            '/showroom/status',
            lambda message: received.append(message.data),
            qos,
        )
        deadline = time.monotonic() + arguments.timeout
        while not received and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    if not received:
        raise SessionError(
            f'{arguments.timeout:.1f} 秒内没有收到 /showroom/status；'
            '请确认 business_mode:=true。')
    try:
        status = json.loads(received[-1])
    except (json.JSONDecodeError, TypeError) as exception:
        raise SessionError(
            f'/showroom/status 不是有效 JSON：{exception}') from exception

    if arguments.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0

    yes_no = {True: '是', False: '否'}
    print(
        f'会话: {state["session_id"]} '
        f'(Domain {state["domain_id"]})')
    print(f'导览机器人: {status.get("guide_state", "UNKNOWN")}')
    print(f'服务机器人: {status.get("coffee_state", "UNKNOWN")}')
    print(
        '已请求咖啡: '
        f'{yes_no.get(status.get("coffee_requested"), "未知")}')
    print(f'配送触发航点: {status.get("coffee_trigger", "UNKNOWN")}')
    print(
        '蓝色已到触发点: '
        f'{yes_no.get(status.get("coffee_trigger_reached"), "未知")}')
    print(f'最近状态来源: {status.get("reason", "UNKNOWN")}')
    return 0


def monitor_target(arguments):
    """Resolve either the current session or a not-yet-started session."""
    explicit_domain = getattr(arguments, 'domain', None)
    if explicit_domain is not None:
        return {
            'session_id': arguments.session_id or '预启动会话',
            'domain_id': explicit_domain,
            'discovery_range': DISCOVERY_RANGE,
        }
    state = current_state()
    if state is None:
        raise SessionError('没有可接入的当前仿真会话。')
    return state


def session_lifecycle(arguments):
    """Return a closure that detects the end of an auto-opened session."""
    parent_pid = getattr(arguments, 'parent_pid', None)
    session_id = getattr(arguments, 'session_id', None)
    if parent_pid is None and not session_id:
        return lambda: False

    parent_ticks = process_start_ticks(parent_pid) if parent_pid else None
    state_path = session_state_path(session_id) if session_id else None
    state_seen = bool(state_path and state_path.exists())

    def finished():
        nonlocal state_seen
        if state_path and state_path.exists():
            state_seen = True
        elif state_seen:
            return True
        if parent_pid and process_start_ticks(parent_pid) != parent_ticks:
            return True
        return False

    return finished


def configure_monitor_environment(state):
    environment = discovery_environment(state['domain_id'])
    for name in ('ROS_DOMAIN_ID', 'ROS_AUTOMATIC_DISCOVERY_RANGE',
                 'ROS_LOG_DIR'):
        os.environ[name] = environment[name]


def show_monitor(arguments):
    state = monitor_target(arguments)
    session_finished = session_lifecycle(arguments)

    configure_monitor_environment(state)

    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String

    received = []

    def monitor_callback(message):
        try:
            document = json.loads(message.data)
            if isinstance(document, dict):
                received[:] = [document]
        except (json.JSONDecodeError, TypeError):
            pass

    node = None
    rclpy.init(args=[])
    try:
        node = rclpy.create_node(f'showroom_monitor_cli_{os.getpid()}')
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        node.create_subscription(
            String, '/showroom/monitor', monitor_callback, qos)

        print(
            f'[monitor] 已接入 Domain {state["domain_id"]}，'
            '正在等待仿真监控数据...',
            flush=True,
        )
        first_deadline = time.monotonic() + arguments.timeout
        displayed = False
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
            if session_finished():
                break
            if received:
                document = received[-1]
                received.clear()
                if not arguments.no_clear and sys.stdout.isatty():
                    print('\033[2J\033[H', end='')
                print(render_monitor(document, state), flush=True)
                displayed = True
                if arguments.once:
                    break
            elif (not displayed and time.monotonic() >= first_deadline
                  and getattr(arguments, 'parent_pid', None) is None):
                raise SessionError(
                    f'{arguments.timeout:.1f} 秒内没有收到 '
                    '/showroom/monitor；请确认仿真已重新构建并启动。')
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if node is not None:
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except (Exception, KeyboardInterrupt):
            pass
    return 0


def show_detail_monitor(arguments):
    """Continuously render the complete monitor JSON document."""
    state = monitor_target(arguments)
    session_finished = session_lifecycle(arguments)
    configure_monitor_environment(state)

    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String

    received = []

    def monitor_callback(message):
        try:
            document = json.loads(message.data)
            if isinstance(document, dict):
                received[:] = [document]
        except (json.JSONDecodeError, TypeError):
            pass

    node = None
    rclpy.init(args=[])
    try:
        node = rclpy.create_node(f'showroom_detail_cli_{os.getpid()}')
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        node.create_subscription(
            String, '/showroom/monitor', monitor_callback, qos)
        print(
            f'[detail-monitor] 已接入 Domain {state["domain_id"]}，'
            '正在等待仿真监控数据...',
            flush=True,
        )

        first_deadline = time.monotonic() + arguments.timeout
        last_display = 0.0
        displayed = False
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
            if session_finished():
                break
            now = time.monotonic()
            if received and (arguments.once
                             or now - last_display >= arguments.interval):
                document = received[-1]
                received.clear()
                if not arguments.no_clear and sys.stdout.isatty():
                    print('\033[2J\033[H', end='')
                print(
                    f'展馆详细监控  |  会话 {state["session_id"]}  |  '
                    f'Domain {state["domain_id"]}\n'
                    + json.dumps(document, ensure_ascii=False, indent=2),
                    flush=True,
                )
                displayed = True
                last_display = now
                if arguments.once:
                    break
            elif (not displayed and now >= first_deadline
                  and getattr(arguments, 'parent_pid', None) is None):
                raise SessionError(
                    f'{arguments.timeout:.1f} 秒内没有收到 '
                    '/showroom/monitor；请确认仿真已重新构建并启动。')
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if node is not None:
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except (Exception, KeyboardInterrupt):
            pass
    return 0


def add_prelaunch_monitor_arguments(parser):
    """Add internal arguments used by start --monitor-windows."""
    parser.add_argument('--domain', type=validate_domain, help=argparse.SUPPRESS)
    parser.add_argument('--session-id', help=argparse.SUPPRESS)
    parser.add_argument('--parent-pid', type=int, help=argparse.SUPPRESS)


def show_environment(_arguments):
    state = current_state()
    if state is None:
        raise SessionError('没有可接入的当前仿真会话。')
    print(f'export ROS_DOMAIN_ID={state["domain_id"]}')
    print(
        'export ROS_AUTOMATIC_DISCOVERY_RANGE='
        f'{state["discovery_range"]}')
    print(f'export DEMO_STAGE_SESSION={state["session_id"]}')
    return 0


def execute_in_session(arguments):
    state = current_state()
    if state is None:
        raise SessionError('没有可接入的当前仿真会话。')
    command = list(arguments.command)
    if command[:1] == ['--']:
        command.pop(0)
    if not command:
        raise SessionError('exec 后需要提供命令。')
    return subprocess.call(
        command,
        env=discovery_environment(state['domain_id']),
    )


def stop_session(_arguments):
    state = current_state()
    if state is None:
        raise SessionError('当前没有活动仿真会话。')
    print(
        f'正在停止 {state["session_id"]} '
        f'(Domain {state["domain_id"]})...')
    stop_process_group(state)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description='为 demo_stage 分配隔离 ROS Domain 并管理仿真会话。')
    subparsers = parser.add_subparsers(dest='action', required=True)

    start = subparsers.add_parser('start', help='自动分配频道并启动仿真')
    start.add_argument(
        '--domain', type=validate_domain,
        help='显式指定空闲 Domain；默认从 81..99 轮换分配')
    start.add_argument(
        '--launch-file', default='showroom_demo.launch.py',
        choices=(
            'showroom.launch.py', 'showroom_demo.launch.py',
            'showroom_nav2.launch.py'),
        help='要启动的 launch 文件')
    start.add_argument(
        '--monitor-windows', action='store_true',
        help='先打开中文监控和详细监控两个终端，再启动 Stage')
    start.add_argument(
        '--monitor-lead-sec', type=float, default=1.0,
        help='监控窗口比 Stage 提前启动的秒数，默认 1.0 秒')
    start.add_argument(
        '--voice', action='store_true',
        help='同时启用本地语音输入输出和 LLM')
    start.add_argument(
        '--voice-rms-threshold', type=float,
        help='配合 --voice 设置语音触发阈值；会话默认 150')
    start.add_argument(
        'launch_arguments', nargs=argparse.REMAINDER,
        help='在 -- 后传递额外 launch 参数')
    start.set_defaults(handler=start_session)

    status = subparsers.add_parser('status', help='显示活动仿真会话')
    status.set_defaults(handler=show_status)

    business_status = subparsers.add_parser(
        'business-status', help='读取两台机器人的当前业务状态')
    business_status.add_argument(
        '--timeout', type=float, default=3.0,
        help='等待 /showroom/status 的秒数，默认 3 秒')
    business_status.add_argument(
        '--json', action='store_true',
        help='输出未经缩略的完整 JSON')
    business_status.set_defaults(handler=show_business_status)

    monitor = subparsers.add_parser(
        'monitor', help='持续显示中文机器人运行看板')
    monitor.add_argument(
        '--once', action='store_true', help='显示一次后退出')
    monitor.add_argument(
        '--timeout', type=float, default=3.0,
        help='等待第一条监控消息的秒数，默认 3 秒')
    monitor.add_argument(
        '--no-clear', action='store_true',
        help='不刷新屏幕，而是连续追加输出')
    add_prelaunch_monitor_arguments(monitor)
    monitor.set_defaults(handler=show_monitor)

    detail_monitor = subparsers.add_parser(
        'detail-monitor', help='持续显示完整的监控 JSON 数据')
    detail_monitor.add_argument(
        '--interval', type=float, default=0.2,
        help='屏幕刷新间隔秒数，默认 0.2 秒')
    detail_monitor.add_argument(
        '--once', action='store_true', help='显示一次后退出')
    detail_monitor.add_argument(
        '--timeout', type=float, default=3.0,
        help='等待第一条监控消息的秒数，默认 3 秒')
    detail_monitor.add_argument(
        '--no-clear', action='store_true',
        help='不刷新屏幕，而是连续追加输出')
    add_prelaunch_monitor_arguments(detail_monitor)
    detail_monitor.set_defaults(handler=show_detail_monitor)

    environment = subparsers.add_parser(
        'env', help='输出当前会话的 shell 环境变量')
    environment.set_defaults(handler=show_environment)

    execute = subparsers.add_parser(
        'exec', help='在当前会话的频道中运行命令')
    execute.add_argument('command', nargs=argparse.REMAINDER)
    execute.set_defaults(handler=execute_in_session)

    stop = subparsers.add_parser('stop', help='停止当前仿真及其整个进程组')
    stop.set_defaults(handler=stop_session)
    return parser


def main():
    parser = build_parser()
    arguments = parser.parse_args()
    try:
        return arguments.handler(arguments)
    except (SessionError, ValueError) as exception:
        print(f'[session] 错误：{exception}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
