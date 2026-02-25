# agent/tools/chat_history.py
"""聊天历史查询工具"""

import json
from typing import Any, TYPE_CHECKING

from .base import Tool

if TYPE_CHECKING:
    from agent.context import AgentContext

DEFAULT_VISIBLE_LIMIT = 30


class ChatHistoryTool(Tool):
    """聊天历史查询工具"""

    @property
    def name(self) -> str:
        return "lookup_chat_history"

    @property
    def description(self) -> str:
        return (
            "查询聊天历史记录。你当前只能看到最近的消息，"
            "调用此工具可以回溯更早的上下文。支持 keywords/range/time 三种模式。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
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
        }

    @property
    def status_text(self) -> str | None:
        return "正在翻阅聊天记录: "

    @property
    def status_arg(self) -> str | None:
        return "keywords"

    async def execute(
        self,
        ctx: "AgentContext",
        mode: str = "",
        keywords: list = None,
        start_offset: int = None,
        end_offset: int = None,
        start_time: str = None,
        end_time: str = None,
        **_,
    ) -> str:
        message_summary = (
            getattr(ctx.robot, "message_summary", None) if ctx.robot else None
        )
        if not message_summary:
            return json.dumps(
                {"error": "消息历史功能不可用"}, ensure_ascii=False
            )

        chat_id = ctx.get_receiver()
        visible_limit = ctx.specific_max_history or DEFAULT_VISIBLE_LIMIT

        # 自动推断模式
        mode = (mode or "").strip().lower()
        if not mode:
            if start_time and end_time:
                mode = "time"
            elif start_offset is not None and end_offset is not None:
                mode = "range"
            else:
                mode = "keywords"

        # keywords 模式
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
                return json.dumps(
                    {"error": "未提供有效关键词", "results": []},
                    ensure_ascii=False,
                )

            search_results = message_summary.search_messages_with_context(
                chat_id=chat_id,
                keywords=cleaned,
                context_window=10,
                max_groups=20,
                exclude_recent=visible_limit,
            )

            segments, lines_seen = [], set()
            for seg in search_results:
                formatted = [
                    l
                    for l in seg.get("formatted_messages", [])
                    if l not in lines_seen
                ]
                lines_seen.update(formatted)
                if formatted:
                    segments.append(
                        {
                            "matched_keywords": seg.get("matched_keywords", []),
                            "messages": formatted,
                        }
                    )

            payload = {
                "segments": segments,
                "returned_groups": len(segments),
                "keywords": cleaned,
            }
            if not segments:
                payload["notice"] = "未找到匹配的消息。"
            return json.dumps(payload, ensure_ascii=False)

        # range 模式
        if mode == "range":
            if start_offset is None or end_offset is None:
                return json.dumps(
                    {"error": "range 模式需要 start_offset 和 end_offset"},
                    ensure_ascii=False,
                )
            try:
                start_offset, end_offset = int(start_offset), int(end_offset)
            except (TypeError, ValueError):
                return json.dumps(
                    {"error": "start_offset 和 end_offset 必须是整数"},
                    ensure_ascii=False,
                )
            if start_offset <= visible_limit or end_offset <= visible_limit:
                return json.dumps(
                    {"error": f"偏移量必须大于 {visible_limit} 以排除当前可见消息"},
                    ensure_ascii=False,
                )
            if start_offset > end_offset:
                start_offset, end_offset = end_offset, start_offset

            result = message_summary.get_messages_by_reverse_range(
                chat_id=chat_id,
                start_offset=start_offset,
                end_offset=end_offset,
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

        # time 模式
        if mode == "time":
            if not start_time or not end_time:
                return json.dumps(
                    {"error": "time 模式需要 start_time 和 end_time"},
                    ensure_ascii=False,
                )

            time_lines = message_summary.get_messages_by_time_window(
                chat_id=chat_id,
                start_time=start_time,
                end_time=end_time,
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
