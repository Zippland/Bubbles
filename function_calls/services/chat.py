"""Chat fallback utilities for Function Call routing."""
from __future__ import annotations

import time
from typing import Optional

from commands.context import MessageContext


def run_chat_fallback(ctx: MessageContext) -> bool:
    """Send a conversational reply using the active chat model.

    This is used when no Function Call handler processes the message.
    Returns True if a reply was sent successfully.
    """
    chat_model = getattr(ctx, "chat", None) or getattr(ctx.robot, "chat", None)
    if not chat_model:
        if ctx.logger:
            ctx.logger.error("聊天兜底失败：没有可用的 chat 模型")
        ctx.send_text("抱歉，我现在无法进行对话。")
        return False

    specific_max_history: Optional[int] = getattr(ctx, "specific_max_history", None)

    if getattr(ctx, "is_quoted_image", False):
        if not _handle_quoted_image(ctx, chat_model):
            return False
        return True

    prompt = _build_prompt(ctx)
    if ctx.logger:
        ctx.logger.info(f"闲聊兜底发送给 AI 的内容:\n{prompt}")

    try:
        answer = chat_model.get_answer(
            question=prompt,
            wxid=ctx.get_receiver(),
            specific_max_history=specific_max_history,
        )
    except Exception as exc:  # pragma: no cover - safety net
        if ctx.logger:
            ctx.logger.error(f"闲聊兜底调用模型失败: {exc}")
        return False

    if not answer:
        if ctx.logger:
            ctx.logger.warning("闲聊兜底返回空响应")
        return False

    at_list = ctx.msg.sender if ctx.is_group else ""
    ctx.send_text(answer, at_list)
    return True


def _build_prompt(ctx: MessageContext) -> str:
    sender_name = ctx.sender_name
    content = ctx.text or ""

    if ctx.robot and hasattr(ctx.robot, "xml_processor"):
        if ctx.is_group:
            msg_data = ctx.robot.xml_processor.extract_quoted_message(ctx.msg)
            formatted = ctx.robot.xml_processor.format_message_for_ai(msg_data, sender_name)
        else:
            msg_data = ctx.robot.xml_processor.extract_private_quoted_message(ctx.msg)
            formatted = ctx.robot.xml_processor.format_message_for_ai(msg_data, sender_name)

        if formatted:
            return formatted

    current_time = time.strftime("%H:%M", time.localtime())
    return f"[{current_time}] {sender_name}: {content or '[空内容]'}"


def _handle_quoted_image(ctx: MessageContext, chat_model) -> bool:
    if ctx.logger:
        ctx.logger.info("检测到引用图片，尝试走模型图片理解能力")

    from ai_providers.ai_chatgpt import ChatGPT  # 避免循环导入

    support_vision = False
    if isinstance(chat_model, ChatGPT):
        support_vision = getattr(chat_model, "support_vision", False)
        if not support_vision and hasattr(chat_model, "model"):
            model_name = getattr(chat_model, "model", "")
            support_vision = model_name in {"gpt-4.1-mini", "gpt-4o"} or "-vision" in model_name

    if not support_vision:
        ctx.send_text("当前模型不支持图片理解，请联系管理员配置支持视觉的模型。")
        return True

    import os

    temp_dir = "temp/image_cache"
    os.makedirs(temp_dir, exist_ok=True)

    try:
        image_path = ctx.wcf.download_image(
            id=ctx.quoted_msg_id,
            extra=ctx.quoted_image_extra,
            dir=temp_dir,
            timeout=30,
        )
    except Exception as exc:  # pragma: no cover - IO 失败
        if ctx.logger:
            ctx.logger.error(f"图片下载失败: {exc}")
        ctx.send_text("抱歉，无法下载图片进行分析。")
        return True

    if not image_path or not os.path.exists(image_path):
        ctx.send_text("抱歉，无法下载图片进行分析。")
        return True

    prompt = ctx.text.strip() or "请详细描述这张图片"

    try:
        response = chat_model.get_image_description(image_path, prompt)
        ctx.send_text(response)
    except Exception as exc:  # pragma: no cover - 模型异常
        if ctx.logger:
            ctx.logger.error(f"图片分析失败: {exc}")
        ctx.send_text(f"分析图片时出错: {exc}")
    finally:
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except OSError:
            if ctx.logger:
                ctx.logger.warning(f"清理临时图片失败: {image_path}")

    return True
