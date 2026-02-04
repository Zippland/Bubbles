"""聊天历史查询工具 —— 从 handlers.py 的内联定义中提取而来。

支持三种查询模式：
  keywords  — 关键词模糊搜索
  range     — 按倒序偏移取连续消息
  time      — 按时间窗口取消息
"""

import json

from tools import Tool, tool_registry

DEFAULT_VISIBLE_LIMIT = 30


def _handle_lookup_chat_history(ctx, mode: str = "", keywords: list = None,
                                start_offset: int = None, end_offset: int = None,
                                start_time: str = None, end_time: str = None,
                                **_) -> str:
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

    # 推断模式
    mode = (mode or "").strip().lower()
    if not mode:
        if start_time and end_time:
            mode = "time"
        elif start_offset is not None and end_offset is not None:
            mode = "range"
        else:
            mode = "keywords"

    # ── keywords ────────────────────────────────────────────
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
            chat_id=chat_id,
            keywords=cleaned,
            context_window=10,
            max_groups=20,
            exclude_recent=visible_limit,
        )

        segments = []
        lines_seen = set()
        for seg in search_results:
            formatted = [l for l in seg.get("formatted_messages", []) if l not in lines_seen]
            lines_seen.update(formatted)
            if formatted:
                segments.append({
                    "matched_keywords": seg.get("matched_keywords", []),
                    "messages": formatted,
                })

        payload = {"segments": segments, "returned_groups": len(segments), "keywords": cleaned}
        if not segments:
            payload["notice"] = "未找到匹配的消息。"
        return json.dumps(payload, ensure_ascii=False)

    # ── range ───────────────────────────────────────────────
    if mode == "range":
        if start_offset is None or end_offset is None:
            return json.dumps({"error": "range 模式需要 start_offset 和 end_offset"}, ensure_ascii=False)
        try:
            start_offset, end_offset = int(start_offset), int(end_offset)
        except (TypeError, ValueError):
            return json.dumps({"error": "start_offset 和 end_offset 必须是整数"}, ensure_ascii=False)

        if start_offset <= visible_limit or end_offset <= visible_limit:
            return json.dumps(
                {"error": f"偏移量必须大于 {visible_limit} 以排除当前可见消息"},
                ensure_ascii=False,
            )
        if start_offset > end_offset:
            start_offset, end_offset = end_offset, start_offset

        result = message_summary.get_messages_by_reverse_range(
            chat_id=chat_id, start_offset=start_offset, end_offset=end_offset,
        )
        payload = {
            "start_offset": result.get("start_offset"),
            "end_offset": result.get("end_offset"),
            "messages": result.get("messages", []),
            "returned_count": result.get("returned_count", 0),
            "total_messages": result.get("total_messages", 0),
        }
        if payload["returned_count"] == 0:
            payload["notice"] = "请求范围内没有消息。"
        return json.dumps(payload, ensure_ascii=False)

    # ── time ────────────────────────────────────────────────
    if mode == "time":
        if not start_time or not end_time:
            return json.dumps({"error": "time 模式需要 start_time 和 end_time"}, ensure_ascii=False)

        time_lines = message_summary.get_messages_by_time_window(
            chat_id=chat_id, start_time=start_time, end_time=end_time,
        )
        payload = {
            "start_time": start_time,
            "end_time": end_time,
            "messages": time_lines,
            "returned_count": len(time_lines),
        }
        if not time_lines:
            payload["notice"] = "该时间范围内没有消息。"
        return json.dumps(payload, ensure_ascii=False)

    return json.dumps({"error": f"不支持的模式: {mode}"}, ensure_ascii=False)


# ── 注册 ────────────────────────────────────────────────────

tool_registry.register(Tool(
    name="lookup_chat_history",
    status_text="正在翻阅聊天记录: ",
    description=(
        "查询聊天历史记录。你当前只能看到最近的消息，调用此工具可以回溯更早的上下文。"
        "支持三种模式：\n"
        "1. mode=\"keywords\" — 用关键词模糊搜索历史消息，返回匹配片段及上下文。"
        "   需要 keywords 数组（2-4 个关键词）。\n"
        "2. mode=\"range\" — 按倒序偏移获取连续消息块。"
        "   需要 start_offset 和 end_offset（均需大于当前可见消息数）。\n"
        "3. mode=\"time\" — 按时间窗口获取消息。"
        "   需要 start_time 和 end_time（格式如 2025-05-01 08:00）。\n"
        "可多次调用，例如先用 keywords 找到锚点，再用 range/time 扩展上下文。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["keywords", "range", "time"],
                "description": "查询模式",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "mode=keywords 时的搜索关键词",
            },
            "start_offset": {
                "type": "integer",
                "description": "mode=range 时的起始偏移（从最新消息倒数）",
            },
            "end_offset": {
                "type": "integer",
                "description": "mode=range 时的结束偏移",
            },
            "start_time": {
                "type": "string",
                "description": "mode=time 时的开始时间 (YYYY-MM-DD HH:MM)",
            },
            "end_time": {
                "type": "string",
                "description": "mode=time 时的结束时间 (YYYY-MM-DD HH:MM)",
            },
        },
        "additionalProperties": False,
    },
    handler=_handle_lookup_chat_history,
))
