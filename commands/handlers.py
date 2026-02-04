import json
import logging
import os
import re
import time as time_mod
from datetime import datetime
from typing import Optional, Match, TYPE_CHECKING

from function.func_persona import build_persona_system_prompt

if TYPE_CHECKING:
    from .context import MessageContext

logger = logging.getLogger(__name__)

DEFAULT_CHAT_HISTORY = 30
DEFAULT_VISIBLE_LIMIT = 30


# ══════════════════════════════════════════════════════════
#  工具 handler 函数
# ══════════════════════════════════════════════════════════

def _web_search(ctx, query: str = "", deep_research: bool = False, **_) -> str:
    perplexity_instance = getattr(ctx.robot, "perplexity", None)
    if not perplexity_instance:
        return json.dumps({"error": "Perplexity 搜索功能不可用，未配置或未初始化"}, ensure_ascii=False)
    if not query:
        return json.dumps({"error": "请提供搜索关键词"}, ensure_ascii=False)
    try:
        response = perplexity_instance.get_answer(query, ctx.get_receiver(), deep_research=deep_research)
        if not response:
            return json.dumps({"error": "搜索无结果"}, ensure_ascii=False)
        cleaned = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        return json.dumps({"result": cleaned or response}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"搜索失败: {e}"}, ensure_ascii=False)


def _reminder_create(ctx, type: str = "once", time: str = "",
                     content: str = "", weekday: int = None, **_) -> str:
    if not hasattr(ctx.robot, "reminder_manager"):
        return json.dumps({"error": "提醒管理器未初始化"}, ensure_ascii=False)
    if not time or not content:
        return json.dumps({"error": "缺少必要字段: time 和 content"}, ensure_ascii=False)
    if len(content.strip()) < 2:
        return json.dumps({"error": "提醒内容太短"}, ensure_ascii=False)

    if type == "once":
        parsed_dt = None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed_dt = datetime.strptime(time, fmt)
                break
            except ValueError:
                continue
        if not parsed_dt:
            return json.dumps({"error": f"once 类型时间格式应为 YYYY-MM-DD HH:MM，收到: {time}"}, ensure_ascii=False)
        if parsed_dt < datetime.now():
            return json.dumps({"error": f"时间 {time} 已过去，请使用未来的时间"}, ensure_ascii=False)
        time = parsed_dt.strftime("%Y-%m-%d %H:%M")
    elif type in ("daily", "weekly"):
        parsed_time = None
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                parsed_time = datetime.strptime(time, fmt)
                break
            except ValueError:
                continue
        if not parsed_time:
            return json.dumps({"error": f"daily/weekly 类型时间格式应为 HH:MM，收到: {time}"}, ensure_ascii=False)
        time = parsed_time.strftime("%H:%M")
    else:
        return json.dumps({"error": f"不支持的提醒类型: {type}"}, ensure_ascii=False)

    if type == "weekly" and (weekday is None or not (isinstance(weekday, int) and 0 <= weekday <= 6)):
        return json.dumps({"error": "weekly 类型需要 weekday 参数 (0=周一 … 6=周日)"}, ensure_ascii=False)

    data = {"type": type, "time": time, "content": content, "extra": {}}
    if weekday is not None:
        data["weekday"] = weekday

    roomid = ctx.msg.roomid if ctx.is_group else None
    success, result = ctx.robot.reminder_manager.add_reminder(ctx.msg.sender, data, roomid=roomid)
    if success:
        type_label = {"once": "一次性", "daily": "每日", "weekly": "每周"}.get(type, type)
        return json.dumps({"success": True, "id": result,
                           "message": f"已创建{type_label}提醒: {time} - {content}"}, ensure_ascii=False)
    return json.dumps({"success": False, "error": result}, ensure_ascii=False)


def _reminder_list(ctx, **_) -> str:
    if not hasattr(ctx.robot, "reminder_manager"):
        return json.dumps({"error": "提醒管理器未初始化"}, ensure_ascii=False)
    reminders = ctx.robot.reminder_manager.list_reminders(ctx.msg.sender)
    if not reminders:
        return json.dumps({"reminders": [], "message": "当前没有任何提醒"}, ensure_ascii=False)
    return json.dumps({"reminders": reminders, "count": len(reminders)}, ensure_ascii=False)


def _reminder_delete(ctx, reminder_id: str = "", delete_all: bool = False, **_) -> str:
    if not hasattr(ctx.robot, "reminder_manager"):
        return json.dumps({"error": "提醒管理器未初始化"}, ensure_ascii=False)
    if delete_all:
        success, message, count = ctx.robot.reminder_manager.delete_all_reminders(ctx.msg.sender)
        return json.dumps({"success": success, "message": message, "deleted_count": count}, ensure_ascii=False)
    if not reminder_id:
        return json.dumps({"error": "请提供 reminder_id，或设置 delete_all=true 删除全部"}, ensure_ascii=False)
    success, message = ctx.robot.reminder_manager.delete_reminder(ctx.msg.sender, reminder_id)
    return json.dumps({"success": success, "message": message}, ensure_ascii=False)


def _lookup_chat_history(ctx, mode: str = "", keywords: list = None,
                         start_offset: int = None, end_offset: int = None,
                         start_time: str = None, end_time: str = None, **_) -> str:
    message_summary = getattr(ctx.robot, "message_summary", None) if ctx.robot else None
    if not message_summary:
        return json.dumps({"error": "消息历史功能不可用"}, ensure_ascii=False)

    chat_id = ctx.get_receiver()
    visible_limit = DEFAULT_VISIBLE_LIMIT
    raw = getattr(ctx, "specific_max_history", None)
    if raw is not None:
        try:
            visible_limit = int(raw)
        except (TypeError, ValueError):
            pass

    mode = (mode or "").strip().lower()
    if not mode:
        if start_time and end_time:
            mode = "time"
        elif start_offset is not None and end_offset is not None:
            mode = "range"
        else:
            mode = "keywords"

    if mode == "keywords":
        if isinstance(keywords, str):
            keywords = [keywords]
        elif not isinstance(keywords, list):
            keywords = []
        cleaned = []
        seen = set()
        for kw in keywords:
            if kw is None:
                continue
            s = str(kw).strip()
            if s and (len(s) > 1 or s.isdigit()):
                low = s.lower()
                if low not in seen:
                    seen.add(low)
                    cleaned.append(s)
        if not cleaned:
            return json.dumps({"error": "未提供有效关键词", "results": []}, ensure_ascii=False)
        search_results = message_summary.search_messages_with_context(
            chat_id=chat_id, keywords=cleaned, context_window=10,
            max_groups=20, exclude_recent=visible_limit,
        )
        segments, lines_seen = [], set()
        for seg in search_results:
            formatted = [l for l in seg.get("formatted_messages", []) if l not in lines_seen]
            lines_seen.update(formatted)
            if formatted:
                segments.append({"matched_keywords": seg.get("matched_keywords", []), "messages": formatted})
        payload = {"segments": segments, "returned_groups": len(segments), "keywords": cleaned}
        if not segments:
            payload["notice"] = "未找到匹配的消息。"
        return json.dumps(payload, ensure_ascii=False)

    if mode == "range":
        if start_offset is None or end_offset is None:
            return json.dumps({"error": "range 模式需要 start_offset 和 end_offset"}, ensure_ascii=False)
        try:
            start_offset, end_offset = int(start_offset), int(end_offset)
        except (TypeError, ValueError):
            return json.dumps({"error": "start_offset 和 end_offset 必须是整数"}, ensure_ascii=False)
        if start_offset <= visible_limit or end_offset <= visible_limit:
            return json.dumps({"error": f"偏移量必须大于 {visible_limit} 以排除当前可见消息"}, ensure_ascii=False)
        if start_offset > end_offset:
            start_offset, end_offset = end_offset, start_offset
        result = message_summary.get_messages_by_reverse_range(
            chat_id=chat_id, start_offset=start_offset, end_offset=end_offset,
        )
        payload = {
            "start_offset": result.get("start_offset"), "end_offset": result.get("end_offset"),
            "messages": result.get("messages", []), "returned_count": result.get("returned_count", 0),
            "total_messages": result.get("total_messages", 0),
        }
        if payload["returned_count"] == 0:
            payload["notice"] = "请求范围内没有消息。"
        return json.dumps(payload, ensure_ascii=False)

    if mode == "time":
        if not start_time or not end_time:
            return json.dumps({"error": "time 模式需要 start_time 和 end_time"}, ensure_ascii=False)
        time_lines = message_summary.get_messages_by_time_window(
            chat_id=chat_id, start_time=start_time, end_time=end_time,
        )
        payload = {"start_time": start_time, "end_time": end_time,
                    "messages": time_lines, "returned_count": len(time_lines)}
        if not time_lines:
            payload["notice"] = "该时间范围内没有消息。"
        return json.dumps(payload, ensure_ascii=False)

    return json.dumps({"error": f"不支持的模式: {mode}"}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════
#  工具注册表
# ══════════════════════════════════════════════════════════

TOOLS = {
    "web_search": {
        "handler": _web_search,
        "description": "在网络上搜索信息。用于回答需要最新数据、实时信息或你不确定的事实性问题。deep_research 仅在问题非常复杂、需要深度研究时才开启。",
        "status_text": "正在联网搜索: ",
        "status_arg": "query",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或问题"},
                "deep_research": {"type": "boolean", "description": "是否启用深度研究模式（耗时较长，仅用于复杂问题）"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "reminder_create": {
        "handler": _reminder_create,
        "description": "创建提醒。支持 once(一次性)、daily(每日)、weekly(每周) 三种类型。当前时间已在对话上下文中提供，请据此计算目标时间。",
        "status_text": "正在设置提醒...",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["once", "daily", "weekly"], "description": "提醒类型"},
                "time": {"type": "string", "description": "once → YYYY-MM-DD HH:MM；daily/weekly → HH:MM"},
                "content": {"type": "string", "description": "提醒内容"},
                "weekday": {"type": "integer", "description": "仅 weekly 需要。0=周一 … 6=周日"},
            },
            "required": ["type", "time", "content"],
            "additionalProperties": False,
        },
    },
    "reminder_list": {
        "handler": _reminder_list,
        "description": "查看当前用户的所有提醒列表。",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "reminder_delete": {
        "handler": _reminder_delete,
        "description": "删除提醒。需要先调用 reminder_list 获取 ID，再用 reminder_id 精确删除；或设置 delete_all=true 一次性删除全部。",
        "parameters": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "string", "description": "要删除的提醒完整 ID"},
                "delete_all": {"type": "boolean", "description": "是否删除该用户全部提醒"},
            },
            "additionalProperties": False,
        },
    },
    "lookup_chat_history": {
        "handler": _lookup_chat_history,
        "description": "查询聊天历史记录。你当前只能看到最近的消息，调用此工具可以回溯更早的上下文。支持 keywords/range/time 三种模式。",
        "status_text": "正在翻阅聊天记录: ",
        "status_arg": "keywords",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["keywords", "range", "time"], "description": "查询模式"},
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "mode=keywords 时的搜索关键词"},
                "start_offset": {"type": "integer", "description": "mode=range 时的起始偏移（从最新消息倒数）"},
                "end_offset": {"type": "integer", "description": "mode=range 时的结束偏移"},
                "start_time": {"type": "string", "description": "mode=time 时的开始时间 (YYYY-MM-DD HH:MM)"},
                "end_time": {"type": "string", "description": "mode=time 时的结束时间 (YYYY-MM-DD HH:MM)"},
            },
            "additionalProperties": False,
        },
    },
}


def _get_openai_tools():
    return [
        {"type": "function", "function": {"name": n, "description": s["description"], "parameters": s["parameters"]}}
        for n, s in TOOLS.items()
    ]


def _create_tool_handler(ctx):
    def _send_status(spec, arguments):
        status = spec.get("status_text", "")
        if not status:
            return
        try:
            arg_name = spec.get("status_arg", "")
            if arg_name:
                val = arguments.get(arg_name)
                if val is not None:
                    if isinstance(val, list):
                        val = "、".join(str(k) for k in val[:3])
                    status = f"{status}{val}"
            ctx.send_text(status, record_message=False)
        except Exception:
            pass

    def handler(tool_name, arguments):
        spec = TOOLS.get(tool_name)
        if not spec:
            return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)
        _send_status(spec, arguments)
        try:
            result = spec["handler"](ctx, **arguments)
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            return result
        except Exception as e:
            logger.error(f"工具 {tool_name} 执行失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    return handler


# ══════════════════════════════════════════════════════════
#  Agent 入口
# ══════════════════════════════════════════════════════════

def handle_chitchat(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """Agent 入口 —— 处理用户消息，LLM 自主决定是否调用工具。"""
    chat_model = None
    if hasattr(ctx, 'chat'):
        chat_model = ctx.chat
    elif ctx.robot and hasattr(ctx.robot, 'chat'):
        chat_model = ctx.robot.chat

    if not chat_model:
        if ctx.logger:
            ctx.logger.error("没有可用的AI模型")
        ctx.send_text("抱歉，我现在无法进行对话。")
        return False

    # 历史消息数量限制
    raw_specific_max_history = getattr(ctx, 'specific_max_history', None)
    specific_max_history = None
    if raw_specific_max_history is not None:
        try:
            specific_max_history = int(raw_specific_max_history)
        except (TypeError, ValueError):
            specific_max_history = None
        if specific_max_history is not None:
            specific_max_history = max(10, min(300, specific_max_history))
    if specific_max_history is None:
        specific_max_history = DEFAULT_CHAT_HISTORY
    setattr(ctx, 'specific_max_history', specific_max_history)

    # ── 引用图片特殊处理 ──────────────────────────────────
    if getattr(ctx, 'is_quoted_image', False):
        return _handle_quoted_image(ctx, chat_model)

    # ── 构建用户消息 ──────────────────────────────────────
    content = ctx.text
    sender_name = ctx.sender_name

    if ctx.robot and hasattr(ctx.robot, "xml_processor"):
        if ctx.is_group:
            msg_data = ctx.robot.xml_processor.extract_quoted_message(ctx.msg)
        else:
            msg_data = ctx.robot.xml_processor.extract_private_quoted_message(ctx.msg)
        q_with_info = ctx.robot.xml_processor.format_message_for_ai(msg_data, sender_name)
        if not q_with_info:
            current_time = time_mod.strftime("%H:%M", time_mod.localtime())
            q_with_info = f"[{current_time}] {sender_name}: {content or '[空内容]'}"
    else:
        current_time = time_mod.strftime("%H:%M", time_mod.localtime())
        q_with_info = f"[{current_time}] {sender_name}: {content or '[空内容]'}"

    is_auto_random_reply = getattr(ctx, 'auto_random_reply', False)

    if ctx.is_group and not ctx.is_at_bot and is_auto_random_reply:
        latest_message_prompt = (
            "# 群聊插话提醒\n"
            "你目前是在群聊里主动接话，没有人点名让你发言。\n"
            "请根据下面这句（或者你任选一句）最新消息插入一条自然、不突兀的中文回复，语气放松随和即可：\n"
            f"\u201c{q_with_info}\u201d\n"
            "不要重复任何已知的内容，提出新的思维碰撞（例如：基于上下文的新问题、不同角度的解释等，但是不要反驳任何内容），也不要显得过于正式。"
        )
    else:
        latest_message_prompt = (
            "# 本轮需要回复的用户及其最新信息\n"
            "请你基于下面这条最新收到的用户讯息（和该用户最近的历史消息），直接面向发送者进行自然的中文回复：\n"
            f"\u201c{q_with_info}\u201d\n"
            "请只针对该用户进行回复。"
        )

    # ── 构建工具列表 ──────────────────────────────────────
    tools = None
    tool_handler = None

    if not is_auto_random_reply:
        openai_tools = _get_openai_tools()
        if openai_tools:
            tools = openai_tools
            tool_handler = _create_tool_handler(ctx)

    # ── 构建系统提示 ──────────────────────────────────────
    persona_text = getattr(ctx, 'persona', None)
    system_prompt_override = None

    tool_guidance = ""
    if tools:
        tool_guidance = (
            "\n\n## 工具使用指引\n"
            "你可以调用工具来辅助回答，以下是决策原则：\n"
            "- 用户询问需要最新信息、实时数据、或你不确定的事实 → 调用 web_search\n"
            "- 用户想设置/查看/删除提醒 → 调用 reminder_create / reminder_list / reminder_delete\n"
            "- 用户提到之前聊过的内容、或你需要回顾更早的对话 → 调用 lookup_chat_history\n"
            "- 日常闲聊、观点讨论、情感交流 → 直接回复，不需要调用任何工具\n"
            "你可以在一次对话中多次调用工具，每次调用的结果会反馈给你继续推理。"
        )

    if persona_text:
        try:
            base_prompt = build_persona_system_prompt(chat_model, persona_text)
            system_prompt_override = base_prompt + tool_guidance if base_prompt else tool_guidance or None
        except Exception as persona_exc:
            if ctx.logger:
                ctx.logger.error(f"构建人设系统提示失败: {persona_exc}", exc_info=True)
            system_prompt_override = tool_guidance or None
    elif tool_guidance:
        system_prompt_override = tool_guidance

    # ── 调用 LLM ─────────────────────────────────────────
    try:
        if ctx.logger:
            tool_names = [t["function"]["name"] for t in tools] if tools else []
            ctx.logger.info(f"Agent 调用: tools={tool_names}")

        rsp = chat_model.get_answer(
            question=latest_message_prompt,
            wxid=ctx.get_receiver(),
            system_prompt_override=system_prompt_override,
            specific_max_history=specific_max_history,
            tools=tools,
            tool_handler=tool_handler,
            tool_max_iterations=20,
        )

        if rsp:
            ctx.send_text(rsp, "")
            return True
        else:
            if ctx.logger:
                ctx.logger.error("无法从AI获得答案")
            return False
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"获取AI回复时出错: {e}", exc_info=True)
        return False


def _handle_quoted_image(ctx, chat_model) -> bool:
    """处理引用图片消息。"""
    if ctx.logger:
        ctx.logger.info("检测到引用图片消息，尝试处理图片内容...")

    from ai_providers.ai_chatgpt import ChatGPT

    support_vision = False
    if isinstance(chat_model, ChatGPT):
        if hasattr(chat_model, 'support_vision') and chat_model.support_vision:
            support_vision = True
        elif hasattr(chat_model, 'model'):
            model_name = getattr(chat_model, 'model', '')
            support_vision = model_name in ("gpt-4.1-mini", "gpt-4o") or "-vision" in model_name

    if not support_vision:
        ctx.send_text("抱歉，当前 AI 模型不支持处理图片。请联系管理员配置支持视觉的模型。")
        return True

    try:
        temp_dir = "temp/image_cache"
        os.makedirs(temp_dir, exist_ok=True)

        image_path = ctx.wcf.download_image(
            id=ctx.quoted_msg_id, extra=ctx.quoted_image_extra,
            dir=temp_dir, timeout=30,
        )

        if not image_path or not os.path.exists(image_path):
            ctx.send_text("抱歉，无法下载图片进行分析。")
            return True

        prompt = ctx.text if ctx.text and ctx.text.strip() else "请详细描述这张图片中的内容"
        response = chat_model.get_image_description(image_path, prompt)
        ctx.send_text(response)

        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception:
            pass
        return True

    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"处理引用图片出错: {e}", exc_info=True)
        ctx.send_text(f"处理图片时发生错误: {str(e)}")
        return True
