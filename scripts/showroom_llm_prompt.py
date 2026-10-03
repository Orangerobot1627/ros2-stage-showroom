#!/usr/bin/env python3
"""Prompt and compact context configuration for the showroom intent model."""

import json
import re


PLACE_ALIASES = (
    (('计算机视觉馆', '计算机视觉展厅', '视觉馆', '视觉展厅', '视觉区'),
     'vision_hall'),
    (('智能机器人馆', '智能机器人展厅', '机器人馆', '机器人展厅', '机器人区'),
     'robotics_hall'),
    (('科技发展历史展区', '科技历史馆', '历史馆', '历史展区', '科技发展史'),
     'technology_history'),
    (('时空科技隧道', '时空隧道', '科技隧道', '隧道'), 'time_tunnel'),
    (('科技舞蹈展厅', '科技舞蹈馆', '舞蹈馆', '舞蹈展厅', '数字艺术馆'),
     'dance_hall'),
    (('智能休息服务区', '咖啡休息区', '休息区', '休息室', '服务区'), 'lounge'),
    (('入馆接待', '接待区', '入馆区', '入口', '门口'), 'reception'),
)


def task_ids_in_text(text):
    """Extract semantic task ids in configured showroom order."""
    return [
        task_id for aliases, task_id in PLACE_ALIASES
        if any(alias in text for alias in aliases)
    ]


def normalize_semantic_result(document, user_text):
    """Make explicit place selection and bypass phrases deterministic."""
    if not isinstance(document, dict):
        return document
    text = str(user_text)
    tasks = task_ids_in_text(text)
    reply = document.get('reply', '')
    selection_request = any(
        word in text for word in ('只看', '只参观', '只去', '只逛'))
    skip_request = any(word in text for word in (
        '不看', '不参观', '不去', '别去', '跳过', '略过', '取消参观'))
    drink_request = any(word in text for word in ('饮料', '咖啡', '水', '果汁'))
    delivery_request = any(word in text for word in ('送', '拿', '来一杯', '给我'))
    drink = 'juice' if '果汁' in text else 'water' if re.search(
        r'(?:一杯|杯|送|拿|来)[^，。]{0,5}水', text) else 'coffee'
    if tasks and (selection_request or skip_request) \
            and drink_request and delivery_request:
        return {
            'intent': 'execute_plan',
            'plan': [
                {
                    'action': 'visit_only' if selection_request else 'skip_task',
                    'tasks': tasks,
                },
                {
                    'action': 'deliver_drink',
                    'drink': drink,
                    'target': tasks[0],
                },
            ],
            'reply': reply,
        }
    if tasks and selection_request:
        return {'intent': 'visit_only', 'tasks': tasks, 'reply': reply}
    if tasks and skip_request:
        return {'intent': 'skip_task', 'tasks': tasks, 'reply': reply}
    if any(word in text for word in ('绕过障碍', '绕开障碍', '绕过去', '避开障碍')):
        robot = 'coffee' if any(word in text for word in (
            '绿色', '咖啡机器人', '服务机器人')) else 'guide'
        return {
            'intent': 'robot_action', 'robot': robot,
            'action': 'bypass_obstacle', 'reply': reply}
    if tasks and drink_request and delivery_request and not any(
            word in text for word in (
                '多待', '多呆', '停留', '待一会', '呆一会', '再看看')):
        return {
            'intent': 'deliver_drink', 'drink': drink,
            'target': tasks[0], 'reply': reply}
    travel_request = any(word in text for word in (
        '去', '前往', '带我去', '带我到', '过去', '导航到')) and not any(
            word in text for word in ('到了吗', '到哪', '怎么去', '如何去'))
    if tasks and travel_request:
        result = {
            'intent': 'temporary_visit',
            'target': tasks[0],
            'reply': reply,
        }
        duration_match = re.search(r'(\d+(?:\.\d+)?)\s*秒', text)
        stay_request = any(word in text for word in (
            '多待', '多呆', '停留', '待一会', '呆一会', '多看一会'))
        if duration_match:
            result['dwell_sec'] = float(duration_match.group(1))
        elif stay_request:
            result['dwell_sec'] = 20.0
        return result
    return document


def normalize_multi_task_result(document, user_text):
    """Repair common small-model omissions for stay-and-drink requests."""
    if not isinstance(document, dict):
        return document
    text = str(user_text)
    stay_request = any(word in text for word in (
        '多待', '多呆', '停留', '待一会', '呆一会', '再看看', '多看一会'))
    drink_request = any(word in text for word in (
        '饮料', '咖啡', '水', '果汁'))
    if not (stay_request and drink_request):
        return document

    duration_match = re.search(r'(\d+(?:\.\d+)?)\s*秒', text)
    pause = {'action': 'pause', 'robot': 'guide'}
    if duration_match:
        pause['duration_sec'] = float(duration_match.group(1))
    drink = 'coffee'
    if '果汁' in text:
        drink = 'juice'
    elif re.search(r'(?:一杯|杯|送|来)[^，。]{0,4}水', text):
        drink = 'water'
    target = 'current_task'
    for aliases, task_id in PLACE_ALIASES:
        if any(alias in text for alias in aliases):
            target = task_id
            break
    return {
        'intent': 'execute_plan',
        'plan': [
            pause,
            {
                'action': 'deliver_drink',
                'drink': drink,
                'target': target,
            },
        ],
        'reply': document.get('reply', ''),
    }


def ground_explanation_result(document, business):
    """Replace explanation prose with configured current-task knowledge."""
    if not isinstance(document, dict):
        return document
    intent = document.get('intent')
    field = {
        'explain_current': 'summary',
        'explain_more': 'detail',
    }.get(intent)
    if field is None:
        return document
    business = business if isinstance(business, dict) else {}
    current_task = business.get('current_task') or {}
    grounded_reply = current_task.get(field)
    if not isinstance(grounded_reply, str) or not grounded_reply.strip():
        return document
    result = dict(document)
    result['reply'] = grounded_reply.strip()
    return result


def compact_context(business, monitor):
    """Keep only state useful to a small local model."""
    business = business if isinstance(business, dict) else {}
    monitor = monitor if isinstance(monitor, dict) else {}
    robots = monitor.get('robots') or {}
    compact_robots = {}
    for robot_id in ('robot_0', 'robot_1'):
        robot = robots.get(robot_id) or {}
        feedback = robot.get('nav2_feedback') or {}
        compact_robots[robot_id] = {
            'navigation_state': robot.get('navigation_state'),
            'current_waypoint': robot.get('current_waypoint'),
            'obstacle_detected': robot.get('obstacle_detected'),
            'front_clearance_m': robot.get('front_clearance_m'),
            'block_count': robot.get('block_count'),
            'distance_remaining_m': feedback.get('distance_remaining_m'),
            'estimated_time_remaining_sec': feedback.get(
                'estimated_time_remaining_sec'),
            'nav2_recovery_count': feedback.get('number_of_recoveries'),
        }
    return {
        'business': {
            'guide_state': business.get('guide_state'),
            'coffee_state': business.get('coffee_state'),
            'coffee_requested': business.get('coffee_requested'),
            'coffee_trigger_reached': business.get('coffee_trigger_reached'),
            'human_override_active': business.get(
                'human_override_active'),
            'human_overrides': business.get('human_overrides'),
            'current_task': business.get('current_task'),
        },
        'robots': compact_robots,
    }


def build_messages(user_text, business=None, monitor=None, knowledge=None):
    """Build a short intent-classification prompt for Qwen3.5 4B."""
    context = compact_context(business, monitor)
    knowledge_text = knowledge or (
        '展馆包括入口、咖啡区、视觉展厅、机器人展厅、时空隧道、'
        '科技舞蹈展厅和休息区。')
    system = f"""你是科技展馆双机器人系统的中文意图分类器。
你只负责把游客原话转换成高层业务意图，绝不能生成速度、坐标或 cmd_vel 指令。

只允许以下 intent：
- start_tour：开始导览。可增加布尔字段 coffee，默认 true
- request_coffee：请求咖啡
- deliver_drink：把 drink 指定的饮料送到 target 指定场馆
- pause_tour：临时暂停蓝色导览机器人，可增加 duration_sec，默认 20 秒
- resume_tour：继续导览
- cancel_all：取消全部任务
- reset：重置业务
- robot_action：控制指定机器人。robot 只能是 guide、coffee、all；action 只能是
  pause、resume、start_default、cancel、bypass_obstacle。pause 可增加 duration_sec，默认 20 秒
- skip_current：游客明确表示对当前展区没兴趣或要求跳过
- repeat_current：从当前任务单元起点重新执行一次
- next_task：正常结束当前内容并进入下一个任务单元
- skip_task：跳过一个或多个指定场馆，tasks 是稳定场馆 ID 数组
- visit_only：只参观指定场馆，tasks 是稳定场馆 ID 数组
- temporary_visit：临时前往 target 场馆，可带 dwell_sec 停留时间。到达或超时后恢复原导览
- explain_current：讲解 current_task，必须用 summary 生成 reply
- explain_more：追问当前内容，必须用 detail 生成更详细的 reply
- execute_plan：一句话同时包含多个任务时使用。plan 是 2..8 个 action 的数组
  - pause：robot 为 guide、coffee 或 all，可带 duration_sec
  - resume：robot 为 guide、coffee 或 all
  - deliver_drink：drink 为 coffee、water、juice 或 drink；target 默认 current_task
  - skip_current、repeat_current、next_task
  - skip_task、visit_only：带 tasks 场馆 ID 数组
  - temporary_visit：带 target，可带 dwell_sec 和 timeout_sec
  - bypass_obstacle：robot 为 guide、coffee 或 all
  - announce：必须带 text
- ask_status：询问机器人位置、进度、障碍或任务状态
- chat：不属于上述业务命令

只输出一个 JSON 对象，不要输出 Markdown、思考过程或额外文字。
普通命令示例：{{"intent":"pause_tour"}}
开始导览示例：{{"intent":"start_tour","coffee":false}}
蓝色机器人等待示例：{{"intent":"pause_tour","duration_sec":20}}
绿色机器人等待示例：{{"intent":"robot_action","robot":"coffee","action":"pause","duration_sec":20}}
绿色机器人立即执行默认配送：{{"intent":"robot_action","robot":"coffee","action":"start_default"}}
跳过当前展区：{{"intent":"skip_current"}}
跳过指定展区：{{"intent":"skip_task","tasks":["robotics_hall"]}}
只看指定展区：{{"intent":"visit_only","tasks":["vision_hall","dance_hall"]}}
临时前往并停留：{{"intent":"temporary_visit","target":"time_tunnel","dwell_sec":20}}
送到指定场馆：{{"intent":"deliver_drink","drink":"coffee","target":"robotics_hall"}}
绕过当前障碍：{{"intent":"robot_action","robot":"guide","action":"bypass_obstacle"}}
重新执行当前展区：{{"intent":"repeat_current"}}
讲解当前展区：{{"intent":"explain_current","reply":"根据 current_task.summary 生成的讲解"}}
深入讲解：{{"intent":"explain_more","reply":"根据 current_task.detail 生成的补充讲解"}}
多任务示例：{{"intent":"execute_plan","plan":[{{"action":"pause","robot":"guide","duration_sec":20}},{{"action":"deliver_drink","drink":"coffee","target":"current_task"}}]}}
除 explain_current 和 explain_more 外，reply 字段不是必需的。
讲解只能使用当前状态中的 current_task 内容，不得编造展品、数字或能力。
同一句话有两个及以上明确动作时，必须使用 execute_plan，不要只返回其中一个 intent。

展馆资料：{knowledge_text}
稳定场馆 ID：reception、technology_history、vision_hall、robotics_hall、time_tunnel、dance_hall、lounge。
当前系统状态：{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}
"""
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user_text.strip()},
    ]
