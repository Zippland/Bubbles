"""
AI路由功能注册
将需要通过AI路由的功能在这里注册
"""
from .ai_router import ai_router
from .context import MessageContext

# ======== 提醒功能 ========
@ai_router.register(
    name="reminder_set",
    description="设置提醒",
    examples=["提醒我明天下午3点开会", "每天早上8点提醒我吃早餐"],
    params_description="时间和内容"
)
def ai_handle_reminder_set(ctx: MessageContext, params: str) -> bool:
    """AI路由的提醒设置处理"""
    if not params.strip():
        at_list = ctx.msg.sender if ctx.is_group else ""
        ctx.send_text("请告诉我需要提醒什么内容和时间呀~", at_list)
        return True
    
    # 调用原有的提醒处理逻辑
    from .handlers import handle_reminder
    
    # 临时修改消息内容以适配原有处理器
    original_content = ctx.msg.content
    ctx.msg.content = f"提醒我{params}"
    
    # handle_reminder不使用match参数，直接传None
    result = handle_reminder(ctx, None)
    
    # 恢复原始内容
    ctx.msg.content = original_content
    
    return result

@ai_router.register(
    name="reminder_list",
    description="查看所有提醒",
    examples=["查看我的提醒", "我有哪些提醒"],
    params_description="无需参数"
)
def ai_handle_reminder_list(ctx: MessageContext, params: str) -> bool:
    """AI路由的提醒列表查看处理"""
    from .handlers import handle_list_reminders
    return handle_list_reminders(ctx, None)

@ai_router.register(
    name="reminder_delete",
    description="删除提醒",
    examples=["删除开会的提醒", "取消明天的提醒"],
    params_description="提醒描述"
)
def ai_handle_reminder_delete(ctx: MessageContext, params: str) -> bool:
    """AI路由的提醒删除处理"""
    # 调用原有的删除提醒逻辑
    from .handlers import handle_delete_reminder
    
    # 临时修改消息内容
    original_content = ctx.msg.content
    ctx.msg.content = f"删除提醒 {params}"
    
    # handle_delete_reminder不使用match参数，直接传None
    result = handle_delete_reminder(ctx, None)
    
    # 恢复原始内容
    ctx.msg.content = original_content
    
    return result

# ======== Perplexity搜索功能 ========
@ai_router.register(
    name="perplexity_search",
    description="在网络上搜索任何问题",
    examples=[
        "搜索Python最新特性",
        "查查机器学习教程",
        '{"query":"量子计算发展", "deep_research": false}'
    ],
    params_description="可直接填写搜索内容；若问题极其复杂且需要长时间深度研究，能接收花费大量时间和费用，请传 JSON，如 {\"query\":\"主题\", \"deep_research\": true}\n只有当问题确实十分复杂、需要长时间联网深度研究时，才在 params 中加入 JSON 字段 \"deep_research\": true；否则保持默认以节省时间和费用。"
)
def ai_handle_perplexity(ctx: MessageContext, params: str) -> bool:
    """AI路由的Perplexity搜索处理"""
    import json

    params = params.strip()

    if not params:
        at_list = ctx.msg.sender if ctx.is_group else ""
        ctx.send_text("请告诉我你想搜索什么内容", at_list)
        return True

    deep_research = False
    query = params
    if params.startswith("{"):
        try:
            parsed = json.loads(params)
            if isinstance(parsed, dict):
                query = parsed.get("query") or parsed.get("q") or ""
                mode = parsed.get("mode") or parsed.get("research_mode")
                deep_research = bool(parsed.get("deep_research") or parsed.get("full_research") or (isinstance(mode, str) and mode.lower() in {"deep", "full", "research"}))
        except json.JSONDecodeError:
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
                q_with_info = f"[{current_time}] {ctx.sender_name}: {params}"
                
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
