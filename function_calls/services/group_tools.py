"""Group related utilities for Function Call handlers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from commands.context import MessageContext


@dataclass
class GroupToolResult:
    success: bool
    message: str


def summarize_messages(ctx: MessageContext) -> GroupToolResult:
    if not ctx.is_group:
        return GroupToolResult(success=True, message="⚠️ 消息总结功能仅支持群聊")

    if not ctx.robot or not hasattr(ctx.robot, "message_summary") or not hasattr(ctx.robot, "chat"):
        return GroupToolResult(success=False, message="⚠️ 消息总结功能不可用")

    try:
        summary = ctx.robot.message_summary.summarize_messages(ctx.msg.roomid, ctx.robot.chat)
        return GroupToolResult(success=True, message=summary)
    except Exception as exc:
        if ctx.logger:
            ctx.logger.error(f"生成消息总结出错: {exc}")
        return GroupToolResult(success=False, message="⚠️ 生成消息总结失败")


def clear_group_messages(ctx: MessageContext) -> GroupToolResult:
    if not ctx.is_group:
        return GroupToolResult(success=True, message="⚠️ 消息历史管理功能仅支持群聊")

    if not ctx.robot or not hasattr(ctx.robot, "message_summary"):
        return GroupToolResult(success=False, message="⚠️ 消息历史管理功能不可用")

    try:
        cleared = ctx.robot.message_summary.clear_message_history(ctx.msg.roomid)
        if cleared:
            return GroupToolResult(success=True, message="✅ 已清除本群的消息历史记录")
        return GroupToolResult(success=True, message="⚠️ 本群没有消息历史记录")
    except Exception as exc:
        if ctx.logger:
            ctx.logger.error(f"清除消息历史出错: {exc}")
        return GroupToolResult(success=False, message="⚠️ 清除消息历史失败")
