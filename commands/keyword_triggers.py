from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from commands.context import MessageContext


@dataclass
class KeywordTriggerDecision:
    reasoning_requested: bool = False
    summary_requested: bool = False


class KeywordTriggerProcessor:
    """Encapsulate keyword-triggered behaviors (e.g., reasoning and summary)."""

    def __init__(self, message_summary: Any, logger: Any) -> None:
        self.message_summary = message_summary
        self.logger = logger

    def evaluate(self, ctx: MessageContext) -> KeywordTriggerDecision:
        raw_text = ctx.text or ""
        text = raw_text.strip()
        reasoning_requested = bool(
            raw_text
            and "想想" in raw_text
            and (not ctx.is_group or ctx.is_at_bot)
        )
        summary_requested = bool(
            ctx.is_group
            and ctx.is_at_bot
            and text == "总结"
        )
        return KeywordTriggerDecision(
            reasoning_requested=reasoning_requested,
            summary_requested=summary_requested,
        )

    def handle_summary(self, ctx: MessageContext) -> bool:
        if not ctx.is_group:
            return False

        if not self.message_summary:
            ctx.send_text("总结功能尚未启用。")
            return True

        chat_model = getattr(ctx, "chat", None)
        try:
            summary_text = self.message_summary.summarize_messages(
                ctx.msg.roomid,
                chat_model=chat_model,
            )
        except Exception as exc:
            if self.logger:
                self.logger.error(f"生成聊天总结失败: {exc}", exc_info=True)
            summary_text = "抱歉，总结时遇到问题，请稍后再试。"

        ctx.send_text(summary_text, "")
        return True
