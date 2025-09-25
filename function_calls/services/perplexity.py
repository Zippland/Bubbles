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

    chat_id = ctx.get_receiver()
    sender_wxid = ctx.msg.sender

    def run_fallback(fallback_prompt: str | None) -> PerplexityResult | None:
        if not fallback_prompt:
            return None

        chat_model = getattr(ctx, 'chat', None) or (getattr(ctx.robot, 'chat', None) if ctx.robot else None)
        if not chat_model:
            return None

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

        return None

    if not perplexity_instance.is_allowed(chat_id, sender_wxid, ctx.is_group):
        fallback_result = run_fallback(perplexity_instance.fallback_prompt)
        if fallback_result:
            return fallback_result
        return PerplexityResult(success=True, messages=["❌ 当前会话未授权使用Perplexity"], handled_externally=False)

    try:
        answer = perplexity_instance.get_answer(query, chat_id)
        sanitized = perplexity_instance.sanitize_response(answer) if answer else ""
        if sanitized:
            return PerplexityResult(success=True, messages=[sanitized], handled_externally=False)

        fallback_result = run_fallback(perplexity_instance.fallback_prompt)
        if fallback_result:
            return fallback_result

        return PerplexityResult(success=True, messages=["❌ Perplexity未返回结果"], handled_externally=False)
    except Exception as exc:
        if ctx.logger:
            ctx.logger.error(f"Perplexity搜索异常: {exc}")

        fallback_result = run_fallback(perplexity_instance.fallback_prompt)
        if fallback_result:
            return fallback_result

        return PerplexityResult(success=True, messages=["❌ Perplexity搜索时发生错误"], handled_externally=False)
