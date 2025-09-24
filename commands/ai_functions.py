"""
AI路由功能注册
将需要通过AI路由的功能在这里注册
"""
import re
import json
import os
from typing import Optional, Match
from datetime import datetime

from .ai_router import ai_router
from .context import MessageContext

# ======== 天气功能 ========
@ai_router.register(
    name="weather_query",
    description="查询城市未来五天的简要天气预报",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "要查询天气的城市名称，如：北京、上海、深圳"
            }
        },
        "required": ["city"]
    }
)
def ai_handle_weather(ctx: MessageContext, city: str, **kwargs) -> bool:
    """AI路由的天气查询处理"""
    city_name = city.strip()
    if not city_name:
        ctx.send_text("🤔 请告诉我你想查询哪个城市的天气")
        return True
    
    # 加载城市代码
    city_codes = {}
    city_code_path = os.path.join(os.path.dirname(__file__), '..', 'function', 'main_city.json')
    try:
        with open(city_code_path, 'r', encoding='utf-8') as f:
            city_codes = json.load(f)
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"加载城市代码文件失败: {e}")
        ctx.send_text("⚠️ 抱歉，天气功能暂时不可用")
        return True
    
    # 查找城市代码
    city_code = city_codes.get(city_name)
    if not city_code:
        # 尝试模糊匹配
        for name, code in city_codes.items():
            if city_name in name:
                city_code = code
                city_name = name
                break
    
    if not city_code:
        ctx.send_text(f"😕 找不到城市 '{city_name}' 的天气信息")
        return True
    
    # 获取天气信息
    try:
        from function.func_weather import Weather
        weather_info = Weather(city_code).get_weather(include_forecast=True)
        ctx.send_text(weather_info)
        return True
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"获取天气信息失败: {e}")
        ctx.send_text(f"😥 获取 {city_name} 天气时遇到问题")
        return True

# ======== 新闻功能 ========
@ai_router.register(
    name="news_query",
    description="获取今日重要新闻和要闻",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def ai_handle_news(ctx: MessageContext, **kwargs) -> bool:
    """AI路由的新闻查询处理"""
    try:
        from function.func_news import News
        news_instance = News()
        is_today, news_content = news_instance.get_important_news()
        
        if is_today:
            ctx.send_text(f"📰 今日要闻来啦：\n{news_content}")
        else:
            if news_content:
                ctx.send_text(f"ℹ️ 今日新闻暂未发布，为您找到最近的一条新闻：\n{news_content}")
            else:
                ctx.send_text("❌ 获取新闻失败，请稍后重试")
        
        return True
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"获取新闻失败: {e}")
        ctx.send_text("❌ 获取新闻时发生错误")
        return True

# ======== 提醒功能 ========
@ai_router.register(
    name="reminder_set",
    description="为用户设置一个新的提醒",
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "提醒的具体内容和时间，如：明天下午3点开会、每天早上8点吃早餐"
            }
        },
        "required": ["content"]
    }
)
def ai_handle_reminder_set(ctx: MessageContext, content: str, **kwargs) -> bool:
    """AI路由的提醒设置处理"""
    if not content.strip():
        at_list = ctx.msg.sender if ctx.is_group else ""
        ctx.send_text("请告诉我需要提醒什么内容和时间呀~", at_list)
        return True

    # 调用原有的提醒处理逻辑
    from .handlers import handle_reminder

    # 临时修改消息内容以适配原有处理器
    original_content = ctx.msg.content
    ctx.msg.content = f"提醒我{content}"

    # handle_reminder不使用match参数，直接传None
    result = handle_reminder(ctx, None)

    # 恢复原始内容
    ctx.msg.content = original_content

    return result

@ai_router.register(
    name="reminder_list",
    description="查看用户已经设置的所有提醒列表",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def ai_handle_reminder_list(ctx: MessageContext, **kwargs) -> bool:
    """AI路由的提醒列表查看处理"""
    from .handlers import handle_list_reminders
    return handle_list_reminders(ctx, None)

@ai_router.register(
    name="reminder_delete",
    description="删除指定的提醒",
    parameters={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "要删除的提醒的描述或关键词，如：开会、早餐、明天的提醒"
            }
        },
        "required": ["description"]
    }
)
def ai_handle_reminder_delete(ctx: MessageContext, description: str, **kwargs) -> bool:
    """AI路由的提醒删除处理"""
    # 调用原有的删除提醒逻辑
    from .handlers import handle_delete_reminder

    # 临时修改消息内容
    original_content = ctx.msg.content
    ctx.msg.content = f"删除提醒 {description}"

    # handle_delete_reminder不使用match参数，直接传None
    result = handle_delete_reminder(ctx, None)

    # 恢复原始内容
    ctx.msg.content = original_content

    return result

# ======== 帮助功能 ========
@ai_router.register(
    name="help",
    description="显示机器人的帮助信息和可用指令列表",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def ai_handle_help(ctx: MessageContext, **kwargs) -> bool:
    """AI路由的帮助处理"""
    help_text = [
        "🤖 泡泡智能助手 🤖",
        "",
        "🌟 我现在支持自然语言交互！你可以用平常说话的方式和我对话：",
        "",
        "【天气查询】",
        "💬 \"北京今天天气怎么样\"",
        "💬 \"上海明天会下雨吗\"",
        "💬 \"查一下深圳的天气预报\"",
        "",
        "【新闻资讯】",
        "💬 \"看看今天的新闻\"",
        "💬 \"有什么重要新闻吗\"",
        "",
        "【智能提醒】",
        "💬 \"提醒我明天下午3点开会\"",
        "💬 \"每天早上8点提醒我吃早餐\"",
        "💬 \"查看我的提醒\"",
        "💬 \"删掉开会的提醒\"",
        "",
        "【智能搜索】",
        "💬 \"搜索Python最新特性\"",
        "💬 \"查一下机器学习教程\"",
        "",
        "【群聊管理】",
        "💬 \"总结一下最近的聊天\" (仅群聊)",
        "💬 \"清除聊天历史\" (仅群聊)",
        "💬 \"查看我的装备\" (仅群聊)",
        "",
        "【娱乐功能】",
        "💬 \"骂一下@张三\" (仅群聊)",
        "",
        "✨ 直接用自然语言告诉我你想做什么，我会智能理解你的意图！",
        "🔧 在群聊中需要@我才能使用功能哦~"
    ]
    help_message = "\n".join(help_text)

    # 发送消息
    ctx.send_text(help_message)
    return True

# ======== 消息管理功能 ========
@ai_router.register(
    name="summary",
    description="总结群聊中最近的聊天消息内容",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def ai_handle_summary(ctx: MessageContext, **kwargs) -> bool:
    """AI路由的消息总结处理"""
    if not ctx.is_group:
        ctx.send_text("⚠️ 消息总结功能仅支持群聊")
        return True

    from .handlers import handle_summary
    return handle_summary(ctx, None)

@ai_router.register(
    name="clear_messages",
    description="清除当前群聊的历史消息记录",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def ai_handle_clear_messages(ctx: MessageContext, **kwargs) -> bool:
    """AI路由的消息历史清除处理"""
    if not ctx.is_group:
        ctx.send_text("⚠️ 消息历史管理功能仅支持群聊")
        return True

    from .handlers import handle_clear_messages
    return handle_clear_messages(ctx, None)

# ======== 决斗功能 ========
@ai_router.register(
    name="check_equipment",
    description="查看玩家在决斗游戏中的魔法装备和道具",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def ai_handle_check_equipment(ctx: MessageContext, **kwargs) -> bool:
    """AI路由的装备查看处理"""
    if not ctx.is_group:
        ctx.send_text("❌ 装备查看功能只支持群聊")
        return True

    from .handlers import handle_check_equipment
    return handle_check_equipment(ctx, None)

# ======== 娱乐功能 ========
@ai_router.register(
    name="insult_user",
    description="骂指定的用户（娱乐功能，无恶意）",
    parameters={
        "type": "object",
        "properties": {
            "target_user": {
                "type": "string",
                "description": "要骂的目标用户的名称或昵称"
            }
        },
        "required": ["target_user"]
    }
)
def ai_handle_insult(ctx: MessageContext, target_user: str, **kwargs) -> bool:
    """AI路由的骂人处理"""
    if not ctx.is_group:
        ctx.send_text("❌ 骂人功能只支持群聊")
        return True

    # 解析参数，提取用户名
    user_name = target_user.strip()
    if not user_name:
        ctx.send_text("🤔 请告诉我要骂谁")
        return True

    # 移除@符号
    user_name = user_name.replace("@", "").strip()

    # 创建一个假的match对象，因为原始处理器需要
    fake_match = type('MockMatch', (), {
        'group': lambda self, n: user_name if n == 1 else None
    })()

    from .handlers import handle_insult
    # 临时修改消息内容以适配原有处理器
    original_content = ctx.msg.content
    ctx.msg.content = f"骂一下@{user_name}"

    result = handle_insult(ctx, fake_match)

    # 恢复原始内容
    ctx.msg.content = original_content

    return result

# ======== Perplexity搜索功能 ========
@ai_router.register(
    name="perplexity_search",
    description="使用Perplexity搜索查询资料并深度研究某个专业问题",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "要搜索的关键词或问题，如：Python最新特性、机器学习教程"
            }
        },
        "required": ["query"]
    }
)
def ai_handle_perplexity(ctx: MessageContext, query: str, **kwargs) -> bool:
    """AI路由的Perplexity搜索处理"""
    if not query.strip():
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
        send_text_func=ctx.send_text
    )
    
    # 如果Perplexity无法处理，使用默认AI
    if not was_handled and fallback_prompt:
        chat_model = getattr(ctx, 'chat', None) or (getattr(ctx.robot, 'chat', None) if ctx.robot else None)
        if chat_model:
            try:
                import time
                current_time = time.strftime("%H:%M", time.localtime())
                q_with_info = f"[{current_time}] {ctx.sender_name}: {query}"
                
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