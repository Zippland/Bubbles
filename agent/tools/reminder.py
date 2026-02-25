# agent/tools/reminder.py
"""提醒工具"""

import json
from datetime import datetime
from typing import Any, TYPE_CHECKING

from .base import Tool

if TYPE_CHECKING:
    from agent.context import AgentContext


class ReminderCreateTool(Tool):
    """创建提醒工具"""

    @property
    def name(self) -> str:
        return "reminder_create"

    @property
    def description(self) -> str:
        return (
            "创建提醒。支持 once(一次性)、daily(每日)、weekly(每周) 三种类型。"
            "当前时间已在对话上下文中提供，请据此计算目标时间。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["once", "daily", "weekly"],
                    "description": "提醒类型",
                },
                "time": {
                    "type": "string",
                    "description": "once → YYYY-MM-DD HH:MM；daily/weekly → HH:MM",
                },
                "content": {
                    "type": "string",
                    "description": "提醒内容",
                },
                "weekday": {
                    "type": "integer",
                    "description": "仅 weekly 需要。0=周一 … 6=周日",
                },
            },
            "required": ["type", "time", "content"],
            "additionalProperties": False,
        }

    @property
    def status_text(self) -> str | None:
        return "正在设置提醒..."

    async def execute(
        self,
        ctx: "AgentContext",
        type: str = "once",
        time: str = "",
        content: str = "",
        weekday: int = None,
        **_,
    ) -> str:
        if not hasattr(ctx.robot, "reminder_manager"):
            return json.dumps(
                {"error": "提醒管理器未初始化"}, ensure_ascii=False
            )

        if not time or not content:
            return json.dumps(
                {"error": "缺少必要字段: time 和 content"}, ensure_ascii=False
            )

        if len(content.strip()) < 2:
            return json.dumps({"error": "提醒内容太短"}, ensure_ascii=False)

        # 验证时间格式
        if type == "once":
            parsed_dt = None
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed_dt = datetime.strptime(time, fmt)
                    break
                except ValueError:
                    continue
            if not parsed_dt:
                return json.dumps(
                    {"error": f"once 类型时间格式应为 YYYY-MM-DD HH:MM，收到: {time}"},
                    ensure_ascii=False,
                )
            if parsed_dt < datetime.now():
                return json.dumps(
                    {"error": f"时间 {time} 已过去，请使用未来的时间"},
                    ensure_ascii=False,
                )
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
                return json.dumps(
                    {"error": f"daily/weekly 类型时间格式应为 HH:MM，收到: {time}"},
                    ensure_ascii=False,
                )
            time = parsed_time.strftime("%H:%M")
        else:
            return json.dumps(
                {"error": f"不支持的提醒类型: {type}"}, ensure_ascii=False
            )

        if type == "weekly" and (
            weekday is None or not (isinstance(weekday, int) and 0 <= weekday <= 6)
        ):
            return json.dumps(
                {"error": "weekly 类型需要 weekday 参数 (0=周一 … 6=周日)"},
                ensure_ascii=False,
            )

        data = {"type": type, "time": time, "content": content, "extra": {}}
        if weekday is not None:
            data["weekday"] = weekday

        roomid = ctx.chat_id if ctx.is_group else None
        success, result = ctx.robot.reminder_manager.add_reminder(
            ctx.sender_wxid, data, roomid=roomid
        )

        if success:
            type_label = {"once": "一次性", "daily": "每日", "weekly": "每周"}.get(
                type, type
            )
            return json.dumps(
                {
                    "success": True,
                    "id": result,
                    "message": f"已创建{type_label}提醒: {time} - {content}",
                },
                ensure_ascii=False,
            )
        return json.dumps({"success": False, "error": result}, ensure_ascii=False)


class ReminderListTool(Tool):
    """查看提醒列表工具"""

    @property
    def name(self) -> str:
        return "reminder_list"

    @property
    def description(self) -> str:
        return "查看当前用户的所有提醒列表。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self, ctx: "AgentContext", **_) -> str:
        if not hasattr(ctx.robot, "reminder_manager"):
            return json.dumps(
                {"error": "提醒管理器未初始化"}, ensure_ascii=False
            )

        reminders = ctx.robot.reminder_manager.list_reminders(ctx.sender_wxid)
        if not reminders:
            return json.dumps(
                {"reminders": [], "message": "当前没有任何提醒"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"reminders": reminders, "count": len(reminders)}, ensure_ascii=False
        )


class ReminderDeleteTool(Tool):
    """删除提醒工具"""

    @property
    def name(self) -> str:
        return "reminder_delete"

    @property
    def description(self) -> str:
        return (
            "删除提醒。需要先调用 reminder_list 获取 ID，"
            "再用 reminder_id 精确删除；或设置 delete_all=true 删除全部。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "要删除的提醒完整 ID",
                },
                "delete_all": {
                    "type": "boolean",
                    "description": "是否删除该用户全部提醒",
                },
            },
            "additionalProperties": False,
        }

    async def execute(
        self,
        ctx: "AgentContext",
        reminder_id: str = "",
        delete_all: bool = False,
        **_,
    ) -> str:
        if not hasattr(ctx.robot, "reminder_manager"):
            return json.dumps(
                {"error": "提醒管理器未初始化"}, ensure_ascii=False
            )

        if delete_all:
            success, message, count = ctx.robot.reminder_manager.delete_all_reminders(
                ctx.sender_wxid
            )
            return json.dumps(
                {"success": success, "message": message, "deleted_count": count},
                ensure_ascii=False,
            )

        if not reminder_id:
            return json.dumps(
                {"error": "请提供 reminder_id，或设置 delete_all=true 删除全部"},
                ensure_ascii=False,
            )

        success, message = ctx.robot.reminder_manager.delete_reminder(
            ctx.sender_wxid, reminder_id
        )
        return json.dumps({"success": success, "message": message}, ensure_ascii=False)
