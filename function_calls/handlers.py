"""Function Call handlers built on top of structured services."""
from __future__ import annotations

from commands.context import MessageContext

from .models import (
    ReminderArgs,
    ReminderListArgs,
    ReminderDeleteArgs,
    PerplexityArgs,
    SummaryArgs,
)
from .registry import tool_function
from .spec import FunctionResult
from .services import (
    create_reminder,
    delete_reminder,
    list_reminders,
    run_perplexity,
    summarize_messages,
)


@tool_function(
    name="reminder_set",
    description="设置提醒",
    examples=["提醒我明天下午3点开会", "每天早上8点提醒我吃早餐"],
    scope="both",
    require_at=True,
)
def handle_reminder_set(ctx: MessageContext, args: ReminderArgs) -> FunctionResult:
    manager = getattr(ctx.robot, "reminder_manager", None)
    at = ctx.msg.sender if ctx.is_group else ""
    if not manager:
        return FunctionResult(handled=True, messages=["❌ 内部错误：提醒管理器未初始化。"], at=at)

    service_result = create_reminder(
        manager=manager,
        sender_wxid=ctx.msg.sender,
        data=args.model_dump(),
        roomid=ctx.msg.roomid if ctx.is_group else None,
    )
    return FunctionResult(handled=True, messages=service_result.messages, at=at if at else "")


@tool_function(
    name="reminder_list",
    description="查看所有提醒",
    examples=["查看我的提醒", "我有哪些提醒", "提醒列表"],
    scope="both",
    require_at=True,
)
def handle_reminder_list(ctx: MessageContext, args: ReminderListArgs) -> FunctionResult:
    manager = getattr(ctx.robot, "reminder_manager", None)
    at = ctx.msg.sender if ctx.is_group else ""
    if not manager:
        return FunctionResult(handled=True, messages=["❌ 内部错误：提醒管理器未初始化。"], at=at)

    service_result = list_reminders(manager, ctx.msg.sender, ctx.all_contacts)
    return FunctionResult(handled=True, messages=service_result.messages, at=at if at else "")


@tool_function(
    name="reminder_delete",
    description="删除提醒",
    examples=["删除开会的提醒", "取消明天的提醒"],
    scope="both",
    require_at=True,
)
def handle_reminder_delete(ctx: MessageContext, args: ReminderDeleteArgs) -> FunctionResult:
    manager = getattr(ctx.robot, "reminder_manager", None)
    at = ctx.msg.sender if ctx.is_group else ""
    if not manager:
        return FunctionResult(handled=True, messages=["❌ 内部错误：提醒管理器未初始化。"], at=at)

    service_result = delete_reminder(manager, ctx.msg.sender, args.reminder_id)
    return FunctionResult(handled=True, messages=service_result.messages, at=at if at else "")


@tool_function(
    name="perplexity_search",
    description="使用Perplexity进行深度搜索查询",
    examples=["搜索Python最新特性", "查查机器学习教程", "ask什么是量子计算"],
    scope="both",
    require_at=True,
)
def handle_perplexity_search(ctx: MessageContext, args: PerplexityArgs) -> FunctionResult:
    service_result = run_perplexity(ctx, args.query)
    if service_result.handled_externally:
        return FunctionResult(handled=True, messages=[])

    at = ctx.msg.sender if ctx.is_group else ""
    return FunctionResult(handled=True, messages=service_result.messages, at=at if at else "")


@tool_function(
    name="summary",
    description="总结群聊最近的消息",
    examples=["summary", "总结"],
    scope="group",
    require_at=True,
)
def handle_summary(ctx: MessageContext, args: SummaryArgs) -> FunctionResult:
    result = summarize_messages(ctx)
    return FunctionResult(handled=True, messages=[result.message])
