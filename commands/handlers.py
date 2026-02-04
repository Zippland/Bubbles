import os
import time as time_mod
from typing import Optional, Match, TYPE_CHECKING

from function.func_persona import build_persona_system_prompt

if TYPE_CHECKING:
    from .context import MessageContext

DEFAULT_CHAT_HISTORY = 30


def handle_chitchat(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    Agent 入口 —— 处理用户消息，LLM 自主决定是否调用工具。
    """
    # 获取对应的AI模型
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

    # 获取特定的历史消息数量限制
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

    # 插嘴模式不使用工具，减少 token 消耗
    if not is_auto_random_reply:
        import skills

        openai_tools = skills.get_openai_tools()
        if openai_tools:
            tools = openai_tools
            tool_handler = skills.create_handler(ctx)

    # ── 构建系统提示 ──────────────────────────────────────
    persona_text = getattr(ctx, 'persona', None)
    system_prompt_override = None

    # 工具使用指引
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

    # ── 调用 LLM（Agent 循环在 _execute_with_tools 中）──
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
