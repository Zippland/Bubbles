"""Perplexity integration helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from commands.context import MessageContext


@dataclass
class PerplexityResult:
    success: bool
    messages: List[str]
    handled_externally: bool = False


def run_perplexity(ctx: MessageContext, query: str) -> PerplexityResult:
    query = query.strip()
    if not query:
        at = ctx.msg.sender if ctx.is_group else ""
        return PerplexityResult(success=True, messages=["请告诉我你想搜索什么内容"], handled_externally=False)

    perplexity_instance = getattr(ctx.robot, 'perplexity', None)
    if not perplexity_instance:
        return PerplexityResult(success=True, messages=["❌ Perplexity搜索功能当前不可用"], handled_externally=False)

    content_for_perplexity = f"ask {query}"
    chat_id = ctx.get_receiver()
    sender_wxid = ctx.msg.sender
    room_id = ctx.msg.roomid if ctx.is_group else None

    was_handled, fallback_prompt = perplexity_instance.process_message(
        content=content_for_perplexity,
        chat_id=chat_id,
        sender=sender_wxid,
        roomid=room_id,
        from_group=ctx.is_group,
        send_text_func=ctx.send_text
    )

    if was_handled:
        return PerplexityResult(success=True, messages=[], handled_externally=True)

    if fallback_prompt:
        chat_model = getattr(ctx, 'chat', None) or (getattr(ctx.robot, 'chat', None) if ctx.robot else None)
        if chat_model:
            try:
                import time
                current_time = time.strftime("%H:%M", time.localtime())
                formatted_question = f"[{current_time}] {ctx.sender_name}: {query}"
                answer = chat_model.get_answer(
                    question=formatted_question,
                    wxid=ctx.get_receiver(),
                    system_prompt_override=fallback_prompt
                )
                if answer:
                    return PerplexityResult(success=True, messages=[answer], handled_externally=False)
            except Exception as exc:
                if ctx.logger:
                    ctx.logger.error(f"默认AI处理失败: {exc}")

    return PerplexityResult(success=True, messages=["❌ Perplexity搜索时发生错误"], handled_externally=False)
