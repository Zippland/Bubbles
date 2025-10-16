"""
AI路由功能注册
将需要通过AI路由的功能在这里注册
"""
from .ai_router import ai_router
from .context import MessageContext

# ======== 提醒功能（一级交给二级路由） ========
@ai_router.register(
    name="reminder_hub",
    description="处理提醒相关需求，会进一步判断是创建、查看还是删除提醒，并自动执行。",
    examples=[
        "提醒我明天上午十点开会",
        "看看今天有哪些提醒",
        "删除下午三点的提醒"
    ],
    params_description="原始提醒类请求内容"
)
def ai_handle_reminder_hub(ctx: MessageContext, params: str) -> bool:
    from .reminder_router import reminder_router
    from .handlers import handle_reminder, handle_list_reminders, handle_delete_reminder

    original_text = params.strip() if isinstance(params, str) and params.strip() else ctx.text or ""
    decision = reminder_router.route(ctx, original_text)

    if not decision:
        at_list = ctx.msg.sender if ctx.is_group else ""
        ctx.send_text("抱歉，暂时无法理解提醒请求，可以换一种说法吗？", at_list)
        return True

    action = decision.action

    if action == "list":
        return handle_list_reminders(ctx, None)

    if action == "delete":
        at_list = ctx.msg.sender if ctx.is_group else ""
        if not decision.success:
            ctx.send_text(decision.message or "❌ 抱歉，无法处理删除提醒的请求。", at_list)
            return True

        if decision.payload is not None:
            setattr(ctx, "_reminder_delete_plan", decision.payload)

        try:
            return handle_delete_reminder(ctx, None)
        finally:
            if hasattr(ctx, "_reminder_delete_plan"):
                delattr(ctx, "_reminder_delete_plan")

    if action == "create":
        at_list = ctx.msg.sender if ctx.is_group else ""
        if not decision.success:
            ctx.send_text(decision.message or "❌ 抱歉，暂时无法理解您的提醒请求。", at_list)
            return True

        if decision.payload is not None:
            setattr(ctx, "_reminder_create_plan", decision.payload)

        try:
            return handle_reminder(ctx, None)
        finally:
            if hasattr(ctx, "_reminder_create_plan"):
                delattr(ctx, "_reminder_create_plan")

    # 兜底处理：无法识别的动作
    at_list = ctx.msg.sender if ctx.is_group else ""
    fallback_message = decision.message or "抱歉，暂时无法处理提醒请求，可以换一种说法吗？"
    ctx.send_text(fallback_message, at_list)
    return True

# ======== Perplexity搜索功能 ========
@ai_router.register(
    name="perplexity_search",
    description="在网络上搜索任何问题",
    examples=[
        "搜索Python最新特性",
        '深圳天气咋样'
        '{"query":"量子计算发展历史的详细研究报告", "deep_research": true}'
    ],
    params_description="可直接填写搜索内容；只有当问题确实十分复杂、需要长时间联网深度研究时，才在 params 中使用 JSON 字段，如 {\"query\":\"主题\", \"deep_research\": true}，否则保持默认以节省时间和费用。"
)
def ai_handle_perplexity(ctx: MessageContext, params: str) -> bool:
    """AI路由的Perplexity搜索处理"""
    import json

    original_params = params

    deep_research = False
    query = ""

    if isinstance(params, dict):
        query = params.get("query") or params.get("q") or ""
        mode = params.get("mode") or params.get("research_mode")
        deep_research = bool(
            params.get("deep_research")
            or params.get("full_research")
            or (isinstance(mode, str) and mode.lower() in {"deep", "full", "research"})
        )
    else:
        params = str(params or "").strip()
        if not params:
            at_list = ctx.msg.sender if ctx.is_group else ""
            ctx.send_text("请告诉我你想搜索什么内容", at_list)
            return True

        if params.startswith("{"):
            try:
                parsed = json.loads(params)
                if isinstance(parsed, dict):
                    query = parsed.get("query") or parsed.get("q") or ""
                    mode = parsed.get("mode") or parsed.get("research_mode")
                    deep_research = bool(
                        parsed.get("deep_research")
                        or parsed.get("full_research")
                        or (isinstance(mode, str) and mode.lower() in {"deep", "full", "research"})
                    )
            except json.JSONDecodeError:
                query = params
        if not query:
            query = params

    if not isinstance(query, str):
        query = str(query or "")
    query = query.strip()
    if not query:
        at_list = ctx.msg.sender if ctx.is_group else ""
        ctx.send_text("请告诉我你想搜索什么内容", at_list)
        return True

    # 获取Perplexity实例
    perplexity_instance = getattr(ctx.robot, 'perplexity', None)
    if not perplexity_instance:
        ctx.send_text("❌ Perplexity搜索功能当前不可用")
        return True

    # 调用Perplexity处理
    content_for_perplexity = f"ask {query}"
    chat_id = ctx.get_receiver()
    sender_wxid = ctx.msg.sender
    room_id = ctx.msg.roomid if ctx.is_group else None
    is_group = ctx.is_group

    was_handled, fallback_prompt = perplexity_instance.process_message(
        content=content_for_perplexity,
        chat_id=chat_id,
        sender=sender_wxid,
        roomid=room_id,
        from_group=is_group,
        send_text_func=ctx.send_text,
        enable_full_research=deep_research
    )
    
    # 如果Perplexity无法处理，使用默认AI
    if not was_handled and fallback_prompt:
        chat_model = getattr(ctx, 'chat', None) or (getattr(ctx.robot, 'chat', None) if ctx.robot else None)
        if chat_model:
            try:
                import time
                current_time = time.strftime("%H:%M", time.localtime())
                if isinstance(original_params, str):
                    formatted_request = original_params
                else:
                    try:
                        formatted_request = json.dumps(original_params, ensure_ascii=False)
                    except Exception:
                        formatted_request = str(original_params)

                q_with_info = f"[{current_time}] {ctx.sender_name}: {formatted_request}"
                
                rsp = chat_model.get_answer(
                    question=q_with_info,
                    wxid=ctx.get_receiver(),
                    system_prompt_override=fallback_prompt
                )
                
                if rsp:
                    at_list = ctx.msg.sender if ctx.is_group else ""
                    ctx.send_text(rsp, at_list)
                    return True
            except Exception as e:
                if ctx.logger:
                    ctx.logger.error(f"默认AI处理失败: {e}")
    
    return was_handled
