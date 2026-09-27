#!/usr/bin/env python3
"""Prompt and compact context configuration for the showroom intent model."""

import json


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
        compact_robots[robot_id] = {
            'navigation_state': robot.get('navigation_state'),
            'current_waypoint': robot.get('current_waypoint'),
            'obstacle_detected': robot.get('obstacle_detected'),
            'front_clearance_m': robot.get('front_clearance_m'),
            'block_count': robot.get('block_count'),
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
- pause_tour：临时暂停蓝色导览机器人，可增加 duration_sec，默认 20 秒
- resume_tour：继续导览
- cancel_all：取消全部任务
- reset：重置业务
- robot_action：控制指定机器人。robot 只能是 guide、coffee、all；action 只能是
  pause、resume、start_default、cancel。pause 可增加 duration_sec，默认 20 秒
- skip_current：游客明确表示对当前展区没兴趣或要求跳过
- repeat_current：从当前任务单元起点重新执行一次
- next_task：正常结束当前内容并进入下一个任务单元
- explain_current：讲解 current_task，必须用 summary 生成 reply
- explain_more：追问当前内容，必须用 detail 生成更详细的 reply
- ask_status：询问机器人位置、进度、障碍或任务状态
- chat：不属于上述业务命令

只输出一个 JSON 对象，不要输出 Markdown、思考过程或额外文字。
普通命令示例：{{"intent":"pause_tour"}}
开始导览示例：{{"intent":"start_tour","coffee":false}}
蓝色机器人等待示例：{{"intent":"pause_tour","duration_sec":20}}
绿色机器人等待示例：{{"intent":"robot_action","robot":"coffee","action":"pause","duration_sec":20}}
绿色机器人立即执行默认配送：{{"intent":"robot_action","robot":"coffee","action":"start_default"}}
跳过当前展区：{{"intent":"skip_current"}}
重新执行当前展区：{{"intent":"repeat_current"}}
讲解当前展区：{{"intent":"explain_current","reply":"根据 current_task.summary 生成的讲解"}}
深入讲解：{{"intent":"explain_more","reply":"根据 current_task.detail 生成的补充讲解"}}
除 explain_current 和 explain_more 外，reply 字段不是必需的。
讲解只能使用当前状态中的 current_task 内容，不得编造展品、数字或能力。

展馆资料：{knowledge_text}
当前系统状态：{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}
"""
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user_text.strip()},
    ]
