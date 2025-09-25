import re
import random
from typing import Optional, Match, Dict, Any
import json # 确保已导入json
from datetime import datetime # 确保已导入datetime
import os # 导入os模块用于文件路径操作
# 前向引用避免循环导入
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .context import MessageContext

def handle_help(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    处理 "帮助" 命令
    
    匹配: info/帮助/指令
    """
    help_text = [
        "🤖 泡泡的指令列表 🤖",
        "",
        "【实用工具】",
        "- 天气/温度 [城市名]",
        "- 天气预报/预报 [城市名]",
        "- 新闻",
        "- ask [问题]",
        "",
        "【提醒】",
        "- 提醒xxxxx：一次性、每日、每周",
        "- 查看提醒/我的提醒/提醒列表",
        "- 删..提醒..",
        "",
        "【群聊工具】",
        "- summary/总结",
        "- clearmessages/清除历史",
        ""
    ]
    help_text = "\n".join(help_text)
    
    # 发送消息
    return ctx.send_text(help_text)


def handle_summary(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    处理 "消息总结" 命令
    
    匹配: summary/总结
    """
    if not ctx.is_group:
        ctx.send_text("⚠️ 消息总结功能仅支持群聊")
        return True
    
    try:
        # 获取群聊ID
        chat_id = ctx.msg.roomid
        
        # 使用MessageSummary生成总结
        if ctx.robot and hasattr(ctx.robot, "message_summary") and hasattr(ctx.robot, "chat"):
            summary = ctx.robot.message_summary.summarize_messages(chat_id, ctx.robot.chat)
            
            # 发送总结
            ctx.send_text(summary)
            
            return True
        else:
            ctx.send_text("⚠️ 消息总结功能不可用")
            return False
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"生成消息总结出错: {e}")
        ctx.send_text("⚠️ 生成消息总结失败")
        return False

def handle_clear_messages(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    处理 "清除消息历史" 命令
    
    匹配: clearmessages/清除消息/清除历史
    """
    if not ctx.is_group:
        ctx.send_text("⚠️ 消息历史管理功能仅支持群聊")
        return True
    
    try:
        # 获取群聊ID
        chat_id = ctx.msg.roomid
        
        # 清除历史
        if ctx.robot and hasattr(ctx.robot, "message_summary"):
            if ctx.robot.message_summary.clear_message_history(chat_id):
                ctx.send_text("✅ 已清除本群的消息历史记录")
            else:
                ctx.send_text("⚠️ 本群没有消息历史记录")
            
            return True
        else:
            ctx.send_text("⚠️ 消息历史管理功能不可用")
            return False
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"清除消息历史出错: {e}")
        ctx.send_text("⚠️ 清除消息历史失败")
        return False

def handle_news_request(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    处理 "新闻" 命令
    
    匹配: 新闻
    """
    if ctx.logger:
        ctx.logger.info(f"收到来自 {ctx.sender_name} (群聊: {ctx.msg.roomid if ctx.is_group else '无'}) 的新闻请求")
        
    try:
        from function.func_news import News
        news_instance = News()
        # 调用方法，接收返回的元组(is_today, news_content)
        is_today, news_content = news_instance.get_important_news()

        receiver = ctx.get_receiver()
        sender_for_at = ctx.msg.sender if ctx.is_group else "" # 群聊中@请求者

        if is_today:
            # 是当天新闻，直接发送
            ctx.send_text(f"📰 今日要闻来啦：\n{news_content}", sender_for_at)
        else:
            # 不是当天新闻或获取失败
            if news_content:
                # 有内容，说明是旧闻
                prompt = "ℹ️ 今日新闻暂未发布，为您找到最近的一条新闻："
                ctx.send_text(f"{prompt}\n{news_content}", sender_for_at)
            else:
                # 内容为空，说明获取彻底失败
                ctx.send_text("❌ 获取新闻失败，请稍后重试或联系管理员。", sender_for_at)

        return True # 无论结果如何，命令本身算成功处理

    except Exception as e:
        if ctx.logger: ctx.logger.error(f"处理新闻请求时出错: {e}")
        receiver = ctx.get_receiver()
        sender_for_at = ctx.msg.sender if ctx.is_group else ""
        ctx.send_text("❌ 获取新闻时发生错误，请稍后重试。", sender_for_at)
        return False # 处理失败

def handle_chitchat(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    处理闲聊，调用AI模型生成回复
    """
    # 获取对应的AI模型
    chat_model = None
    if hasattr(ctx, 'chat'):
        chat_model = ctx.chat
    elif ctx.robot and hasattr(ctx.robot, 'chat'):
        chat_model = ctx.robot.chat
    
    if not chat_model:
        if ctx.logger:
            ctx.logger.error("没有可用的AI模型处理闲聊")
        ctx.send_text("抱歉，我现在无法进行对话。")
        return False
    
    # 获取特定的历史消息数量限制
    specific_max_history = getattr(ctx, 'specific_max_history', None)
    if ctx.logger and specific_max_history is not None:
        ctx.logger.debug(f"为 {ctx.get_receiver()} 使用特定历史限制: {specific_max_history}")
    
    #  处理引用图片情况
    if getattr(ctx, 'is_quoted_image', False):
        ctx.logger.info("检测到引用图片消息，尝试处理图片内容...")
        
        import os
        from ai_providers.ai_chatgpt import ChatGPT
        
        # 确保是 ChatGPT 类型且支持图片处理
        support_vision = False
        if isinstance(chat_model, ChatGPT):
            if hasattr(chat_model, 'support_vision') and chat_model.support_vision:
                support_vision = True
            else:
                # 检查模型名称判断是否支持视觉
                if hasattr(chat_model, 'model'):
                    model_name = getattr(chat_model, 'model', '')
                    support_vision = model_name == "gpt-4.1-mini" or model_name == "gpt-4o" or "-vision" in model_name
        
        if not support_vision:
            ctx.send_text("抱歉，当前 AI 模型不支持处理图片。请联系管理员配置支持视觉的模型 (如 gpt-4-vision-preview、gpt-4o 等)。")
            return True
        
        # 下载图片并处理
        try:
            # 创建临时目录
            temp_dir = "temp/image_cache"
            os.makedirs(temp_dir, exist_ok=True)
            
            # 下载图片
            ctx.logger.info(f"正在下载引用图片: msg_id={ctx.quoted_msg_id}")
            image_path = ctx.wcf.download_image(
                id=ctx.quoted_msg_id,
                extra=ctx.quoted_image_extra,
                dir=temp_dir,
                timeout=30
            )
            
            if not image_path or not os.path.exists(image_path):
                ctx.logger.error(f"图片下载失败: {image_path}")
                ctx.send_text("抱歉，无法下载图片进行分析。")
                return True
            
            ctx.logger.info(f"图片下载成功: {image_path}，准备分析...")
            
            # 调用 ChatGPT 分析图片
            try:
                # 根据用户的提问构建 prompt
                prompt = ctx.text
                if not prompt or prompt.strip() == "":
                    prompt = "请详细描述这张图片中的内容"
                
                # 调用图片分析函数
                response = chat_model.get_image_description(image_path, prompt)
                ctx.send_text(response)
                
                ctx.logger.info("图片分析完成并已发送回复")
            except Exception as e:
                ctx.logger.error(f"分析图片时出错: {e}")
                ctx.send_text(f"分析图片时出错: {str(e)}")
            
            # 清理临时图片
            try:
                if os.path.exists(image_path):
                    os.remove(image_path)
                    ctx.logger.info(f"临时图片已删除: {image_path}")
            except Exception as e:
                ctx.logger.error(f"删除临时图片出错: {e}")
            
            return True  # 已处理，不执行后续的普通文本处理流程
            
        except Exception as e:
            ctx.logger.error(f"处理引用图片过程中出错: {e}")
            ctx.send_text(f"处理图片时发生错误: {str(e)}")
            return True  # 已处理，即使出错也不执行后续普通文本处理
    
    # 获取消息内容
    content = ctx.text
    sender_name = ctx.sender_name
    
    # 使用XML处理器格式化消息
    if ctx.robot and hasattr(ctx.robot, "xml_processor"):
        # 创建格式化的聊天内容（带有引用消息等）
        if ctx.is_group:
            # 处理群聊消息
            msg_data = ctx.robot.xml_processor.extract_quoted_message(ctx.msg)
            q_with_info = ctx.robot.xml_processor.format_message_for_ai(msg_data, sender_name)
        else:
            # 处理私聊消息
            msg_data = ctx.robot.xml_processor.extract_private_quoted_message(ctx.msg)
            q_with_info = ctx.robot.xml_processor.format_message_for_ai(msg_data, sender_name)
        
        if not q_with_info:
            import time
            current_time = time.strftime("%H:%M", time.localtime())
            q_with_info = f"[{current_time}] {sender_name}: {content or '[空内容]'}"
    else:
        # 简单格式化
        import time
        current_time = time.strftime("%H:%M", time.localtime())
        q_with_info = f"[{current_time}] {sender_name}: {content or '[空内容]'}"
    
    # 获取AI回复
    try:
        if ctx.logger:
            ctx.logger.info(f"【发送内容】将以下消息发送给AI: \n{q_with_info}")
        
        # 调用AI模型，传递特定历史限制
        rsp = chat_model.get_answer(
            question=q_with_info, 
            wxid=ctx.get_receiver(),
            specific_max_history=specific_max_history
        )
        
        if rsp:
            # 发送回复
            at_list = ctx.msg.sender if ctx.is_group else ""
            ctx.send_text(rsp, at_list)
            
            return True
        else:
            if ctx.logger:
                ctx.logger.error("无法从AI获得答案")
            return False
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"获取AI回复时出错: {e}")
        return False

def handle_insult(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    处理 "骂人" 命令
    
    匹配: 骂一下@XX
    """
    if not ctx.is_group:
        ctx.send_text("❌ 骂人功能只支持群聊哦~")
        return True
    
    if not match:
        return False
    
    # 获取目标名称
    target_mention_name = match.group(1).strip()
    
    if ctx.logger:
        ctx.logger.info(f"群聊 {ctx.msg.roomid} 中检测到骂人指令，提及目标：{target_mention_name}")
    
    # 默认使用提及的名称
    actual_target_name = target_mention_name  
    target_wxid = None
    
    # 尝试查找实际群成员昵称和wxid
    try:
        found = False
        for wxid, name in ctx.room_members.items():
            # 优先完全匹配，其次部分匹配
            if target_mention_name == name:
                target_wxid = wxid
                actual_target_name = name
                found = True
                break
        if not found:  # 如果完全匹配不到，再尝试部分匹配
            for wxid, name in ctx.room_members.items():
                if target_mention_name in name:
                    target_wxid = wxid
                    actual_target_name = name
                    break
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"查找群成员信息时出错: {e}")
        # 出错时继续使用提及的名称
    
    # 禁止骂机器人自己
    if target_wxid and target_wxid == ctx.robot_wxid:
        ctx.send_text("😅 不行，我不能骂我自己。")
        return True
    
    # 即使找不到wxid，仍然尝试使用提及的名字骂
    try:
        from function.func_insult import generate_random_insult
        insult_text = generate_random_insult(actual_target_name)
        ctx.send_text(insult_text)
        
        if ctx.logger:
            ctx.logger.info(f"已发送骂人消息至群 {ctx.msg.roomid}，目标: {actual_target_name}")
        
        return True
    except ImportError:
        if ctx.logger:
            ctx.logger.error("无法导入 func_insult 模块。")
        ctx.send_text("Oops，我的骂人模块好像坏了...")
        return True
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"生成或发送骂人消息时出错: {e}")
        ctx.send_text("呃，我想骂但出错了...")
        return True

def handle_perplexity_ask(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    处理 "ask" 命令，调用 Perplexity AI

    匹配: ask [问题内容]
    """
    if not match:  # 理论上正则匹配成功才会被调用，但加个检查更安全
        return False

    # 1. 尝试从 Robot 实例获取 Perplexity 实例
    perplexity_instance = getattr(ctx.robot, 'perplexity', None)
    
    # 2. 检查 Perplexity 实例是否存在
    if not perplexity_instance:
        if ctx.logger:
            ctx.logger.warning("尝试调用 Perplexity，但实例未初始化或未配置。")
        ctx.send_text("❌ Perplexity 功能当前不可用或未正确配置。")
        return True  # 命令已被处理（错误处理也是处理）

    # 3. 从匹配结果中提取问题内容
    prompt = match.group(1).strip()
    if not prompt:  # 如果 'ask' 后面没有内容
        ctx.send_text("请在 'ask' 后面加上您想问的问题。", ctx.msg.sender if ctx.is_group else None)
        return True  # 命令已被处理

    # 4. 准备调用 Perplexity 实例的 process_message 方法
    if ctx.logger:
        ctx.logger.info(f"检测到 Perplexity 请求，发送者: {ctx.sender_name}, 问题: {prompt[:50]}...")

    # 准备参数并调用 process_message
    # 确保无论用户输入有没有空格，都以标准格式"ask 问题"传给process_message
    content_for_perplexity = f"ask {prompt}"  # 重构包含触发词的内容
    chat_id = ctx.get_receiver()
    sender_wxid = ctx.msg.sender
    room_id = ctx.msg.roomid if ctx.is_group else None
    is_group = ctx.is_group
    
    # 5. 调用 process_message 并返回其结果
    was_handled, fallback_prompt = perplexity_instance.process_message(
        content=content_for_perplexity,
        chat_id=chat_id,
        sender=sender_wxid,
        roomid=room_id,
        from_group=is_group,
        send_text_func=ctx.send_text
    )
    
    # 6. 如果没有被处理且有备选prompt，使用默认AI处理
    if not was_handled and fallback_prompt:
        if ctx.logger:
            ctx.logger.info(f"使用备选prompt '{fallback_prompt[:20]}...' 调用默认AI处理")
        
        # 获取当前选定的AI模型
        chat_model = None
        if hasattr(ctx, 'chat'):
            chat_model = ctx.chat
        elif ctx.robot and hasattr(ctx.robot, 'chat'):
            chat_model = ctx.robot.chat
        
        if chat_model:
            # 使用与 handle_chitchat 类似的逻辑，但使用备选prompt
            try:
                # 格式化消息，与 handle_chitchat 保持一致
                if ctx.robot and hasattr(ctx.robot, "xml_processor"):
                    if ctx.is_group:
                        msg_data = ctx.robot.xml_processor.extract_quoted_message(ctx.msg)
                        q_with_info = ctx.robot.xml_processor.format_message_for_ai(msg_data, ctx.sender_name)
                    else:
                        msg_data = ctx.robot.xml_processor.extract_private_quoted_message(ctx.msg)
                        q_with_info = ctx.robot.xml_processor.format_message_for_ai(msg_data, ctx.sender_name)
                    
                    if not q_with_info:
                        import time
                        current_time = time.strftime("%H:%M", time.localtime())
                        q_with_info = f"[{current_time}] {ctx.sender_name}: {prompt or '[空内容]'}"
                else:
                    import time
                    current_time = time.strftime("%H:%M", time.localtime())
                    q_with_info = f"[{current_time}] {ctx.sender_name}: {prompt or '[空内容]'}"
                
                if ctx.logger:
                    ctx.logger.info(f"发送给默认AI的消息内容: {q_with_info}")
                
                # 调用 AI 模型时传入备选 prompt
                # 需要调整 get_answer 方法以支持 system_prompt_override 参数
                # 这里我们假设已对各AI模型实现了这个参数
                specific_max_history = getattr(ctx, 'specific_max_history', None)
                rsp = chat_model.get_answer(
                    question=q_with_info, 
                    wxid=ctx.get_receiver(), 
                    system_prompt_override=fallback_prompt,
                    specific_max_history=specific_max_history
                )
                
                if rsp:
                    # 发送回复
                    at_list = ctx.msg.sender if ctx.is_group else ""
                    ctx.send_text(rsp, at_list)
                    
                    return True
                else:
                    if ctx.logger:
                        ctx.logger.error("无法从默认AI获得答案")
            except Exception as e:
                if ctx.logger:
                    ctx.logger.error(f"使用备选prompt调用默认AI时出错: {e}")
    
    return was_handled 

def handle_reminder(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """处理来自私聊或群聊的 '提醒' 命令，支持批量添加多个提醒"""
    # 2. 获取用户输入的提醒内容 (现在从完整消息获取)
    raw_text = ctx.msg.content.strip() # 修改：从 ctx.msg.content 获取
    if not raw_text: # 修改：仅检查是否为空
        # 在群聊中@用户回复
        at_list = ctx.msg.sender if ctx.is_group else ""
        ctx.send_text("请告诉我需要提醒什么内容和时间呀~ (例如：提醒我明天下午3点开会)", at_list) 
        return True

    # 3. 构造给 AI 的 Prompt，更新为支持批量提醒
    sys_prompt = """
你是提醒解析助手。请仔细分析用户输入的提醒信息，**识别其中可能包含的所有独立提醒请求**。将所有成功解析的提醒严格按照以下 JSON **数组** 格式输出结果，数组中的每个元素代表一个独立的提醒:
[
  {{
    "type": "once" | "daily" | "weekly",                 // 提醒类型: "once" (一次性) 或 "daily" (每日重复) 或 "weekly" (每周重复)
    "time": "YYYY-MM-DD HH:MM" | "HH:MM",     // "once"类型必须是 'YYYY-MM-DD HH:MM' 格式, "daily"与"weekly"类型必须是 'HH:MM' 格式。时间必须是未来的。
    "content": "提醒的具体内容文本",
    "weekday": 0-6,                           // 仅当 type="weekly" 时需要，周一=0, 周二=1, ..., 周日=6
    "extra": {{}}                              // 保留字段，目前为空对象即可
  }},
  // ... 可能有更多提醒对象 ...
]

**重要:** 你的回复必须仅包含有效的JSON数组，不要包含任何其他说明文字。所有JSON中的布尔值、数字应该没有引号，字符串需要有引号。

- **仔细分析用户输入，识别所有独立的提醒请求。**
- 对每一个识别出的提醒，判断其类型 (`once`, `daily`, `weekly`) 并计算准确时间。
- "once"类型时间必须是 'YYYY-MM-DD HH:MM' 格式, "daily"/"weekly"类型必须是 'HH:MM' 格式。时间必须是未来的。
- "weekly"类型必须提供 weekday (周一=0...周日=6)。
- **将所有解析成功的提醒对象放入一个 JSON 数组中返回。**
- 如果只识别出一个提醒，返回包含单个元素的数组。
- **如果无法识别出任何有效提醒，返回空数组 `[]`。**
- 如果用户输入的某个提醒部分信息不完整或格式错误，请尝试解析其他部分，并在最终数组中仅包含解析成功的提醒。
- 输出结果必须是纯 JSON 数组，不包含任何其他说明文字。

当前准确时间是：{current_datetime}
"""
    current_dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_prompt = sys_prompt.format(current_datetime=current_dt_str)

    # 4. 调用AI模型并解析
    q_for_ai = f"请解析以下用户提醒，识别所有独立的提醒请求:\n{raw_text}"
    try:
        # 检查AI模型
        if not hasattr(ctx, 'chat') or not ctx.chat:
            raise ValueError("当前上下文中没有可用的AI模型")
            
        # 获取AI回答
        at_list = ctx.msg.sender if ctx.is_group else ""
        
        # 实现最多尝试3次解析AI回复的逻辑
        max_retries = 3
        retry_count = 0
        parsed_reminders = [] # 初始化为空列表
        ai_parsing_success = False
        
        while retry_count < max_retries and not ai_parsing_success:
            # 如果是重试，更新提示信息
            if retry_count > 0:
                enhanced_prompt = sys_prompt + f"\n\n**重要提示:** 这是第{retry_count+1}次尝试。你之前的回复格式有误，无法被解析为有效的JSON。请确保你的回复仅包含有效的JSON数组，没有其他任何文字。"
                formatted_prompt = enhanced_prompt.format(current_datetime=current_dt_str)
                # 在重试时提供更明确的信息
                retry_q = f"请再次解析以下提醒，并返回严格的JSON数组格式(第{retry_count+1}次尝试):\n{raw_text}"
                q_for_ai = retry_q
            
            ai_response = ctx.chat.get_answer(q_for_ai, ctx.get_receiver(), system_prompt_override=formatted_prompt)
            
            # 尝试匹配 [...] 或 {...} (兼容单个提醒的情况，但优先列表)
            json_match_list = re.search(r'\[.*\]', ai_response, re.DOTALL)
            json_match_obj = re.search(r'\{.*\}', ai_response, re.DOTALL)
            
            json_str = None
            if json_match_list:
                json_str = json_match_list.group(0)
            elif json_match_obj: # 如果没找到列表，尝试找单个对象 (增加兼容性)
                 json_str = f"[{json_match_obj.group(0)}]" # 将单个对象包装成数组
            else:
                json_str = ai_response # 如果都找不到，直接尝试解析原始回复
            
            try:
                # 尝试解析JSON
                parsed_data = json.loads(json_str)
                # 确保解析结果是一个列表
                if isinstance(parsed_data, dict):
                    parsed_reminders = [parsed_data] # 包装成单元素列表
                elif isinstance(parsed_data, list):
                    parsed_reminders = parsed_data # 本身就是列表
                else:
                    # 解析结果不是列表也不是字典，无法处理
                    raise ValueError("AI 返回的不是有效的 JSON 列表或对象")
                
                # 如果能到这里，说明解析成功
                ai_parsing_success = True
                
            except (json.JSONDecodeError, ValueError) as e:
                # JSON解析失败
                retry_count += 1
                if ctx.logger: 
                    ctx.logger.warning(f"AI 返回 JSON 解析失败(第{retry_count}次尝试): {ai_response}, 错误: {str(e)}")
                
                if retry_count >= max_retries:
                    # 达到最大重试次数，返回错误
                    ctx.send_text(f"❌ 抱歉，无法理解您的提醒请求。请尝试换一种方式表达，或分开设置多个提醒。", at_list)
                    if ctx.logger: ctx.logger.error(f"解析AI回复失败，已达到最大重试次数({max_retries}): {ai_response}")
                    return True
                # 否则继续下一次循环重试
        
        # 检查 ReminderManager 是否存在
        if not hasattr(ctx.robot, 'reminder_manager'):
            ctx.send_text("❌ 内部错误：提醒管理器未初始化。", at_list)
            if ctx.logger: ctx.logger.error("handle_reminder 无法访问 ctx.robot.reminder_manager")
            return True

        # 如果AI返回空列表，告知用户
        if not parsed_reminders:
            ctx.send_text("🤔 嗯... 我好像没太明白您想设置什么提醒，可以换种方式再说一次吗？", at_list)
            return True

        # 批量处理提醒 
        results = [] # 用于存储每个提醒的处理结果
        roomid = ctx.msg.roomid if ctx.is_group else None

        for index, data in enumerate(parsed_reminders):
            reminder_label = f"提醒{index+1}" # 给每个提醒一个标签，方便反馈
            validation_error = None # 存储验证错误信息

            # **验证单个提醒数据**
            if not isinstance(data, dict):
                validation_error = "格式错误 (不是有效的提醒对象)"
            elif not data.get("type") or not data.get("time") or not data.get("content"):
                validation_error = "缺少必要字段(类型/时间/内容)"
            elif len(data.get("content", "").strip()) < 2:
                validation_error = "提醒内容太短"
            else:
                # 验证时间格式
                try:
                    if data["type"] == "once":
                        dt = datetime.strptime(data["time"], "%Y-%m-%d %H:%M")
                        if dt < datetime.now():
                             validation_error = f"时间 ({data['time']}) 必须是未来的时间"
                    elif data["type"] in ["daily", "weekly"]:
                         datetime.strptime(data["time"], "%H:%M") # 仅校验格式
                    else:
                         validation_error = f"不支持的提醒类型: {data.get('type')}"
                except ValueError:
                     validation_error = f"时间格式错误 ({data.get('time', '')})"

                # 验证周提醒 (如果类型是 weekly 且无验证错误)
                if not validation_error and data["type"] == "weekly":
                    if not (isinstance(data.get("weekday"), int) and 0 <= data.get("weekday") <= 6):
                        validation_error = "每周提醒需要指定周几(0-6)"

            # 如果验证通过，尝试添加到数据库
            if not validation_error:
                try:
                    success, result_or_id = ctx.robot.reminder_manager.add_reminder(ctx.msg.sender, data, roomid=roomid)
                    if success:
                        results.append({"label": reminder_label, "success": True, "id": result_or_id, "data": data})
                        if ctx.logger: ctx.logger.info(f"成功添加提醒 {result_or_id} for {ctx.msg.sender} (来自批量处理)")
                    else:
                        # add_reminder 返回错误信息
                        results.append({"label": reminder_label, "success": False, "error": result_or_id, "data": data})
                        if ctx.logger: ctx.logger.warning(f"添加提醒失败 (来自批量处理): {result_or_id}")
                except Exception as db_e:
                    # 捕获 add_reminder 可能抛出的其他异常
                    error_msg = f"数据库错误: {db_e}"
                    results.append({"label": reminder_label, "success": False, "error": error_msg, "data": data})
                    if ctx.logger: ctx.logger.error(f"添加提醒时数据库出错 (来自批量处理): {db_e}", exc_info=True)
            else:
                # 验证失败
                results.append({"label": reminder_label, "success": False, "error": validation_error, "data": data})
                if ctx.logger: ctx.logger.warning(f"提醒数据验证失败 ({reminder_label}): {validation_error} - Data: {data}")

        # 构建汇总反馈消息 
        reply_parts = []
        successful_count = sum(1 for res in results if res["success"])
        failed_count = len(results) - successful_count
        
        # 添加总览信息
        if len(results) > 1:  # 只有多个提醒时才需要总览
            if successful_count > 0 and failed_count > 0:
                reply_parts.append(f"✅ 已设置 {successful_count} 个提醒，{failed_count} 个设置失败：\n")
            elif successful_count > 0:
                reply_parts.append(f"✅ 已设置 {successful_count} 个提醒：\n")
            else:
                reply_parts.append(f"❌ 抱歉，所有 {len(results)} 个提醒设置均失败：\n")
                
        # 添加每个提醒的详细信息
        for res in results:
            content_preview = res['data'].get('content', '未知内容')
            # 如果内容太长，截取前20个字符加省略号
            if len(content_preview) > 20:
                content_preview = content_preview[:20] + "..."
                
            if res["success"]:
                reminder_id = res['id']
                type_str = {"once": "一次性", "daily": "每日", "weekly": "每周"}.get(res['data'].get('type'), "未知")
                time_display = res['data'].get("time", "?")
                
                # 为周提醒格式化显示
                if res['data'].get("type") == "weekly" and "weekday" in res['data']:
                    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                    if 0 <= res['data']["weekday"] <= 6:
                        time_display = f"{weekdays[res['data']['weekday']]} {time_display}"
                
                # 单个提醒或多个提醒的第一个，不需要标签
                if len(results) == 1:
                    reply_parts.append(f"✅ 已为您设置{type_str}提醒:\n" 
                                      f"时间: {time_display}\n" 
                                      f"内容: {res['data'].get('content', '无')}")
                else:
                    reply_parts.append(f"✅ {res['label']}: {type_str}\n {time_display} - \"{content_preview}\"")
            else:
                # 失败的提醒
                if len(results) == 1:
                    reply_parts.append(f"❌ 设置提醒失败: {res['error']}")
                else:
                    reply_parts.append(f"❌ {res['label']}: \"{content_preview}\" - {res['error']}")

        # 发送汇总消息
        ctx.send_text("\n".join(reply_parts), at_list)

        return True # 命令处理流程结束

    except Exception as e: # 捕获代码块顶层的其他潜在错误
        at_list = ctx.msg.sender if ctx.is_group else ""
        error_message = f"处理提醒时发生意外错误: {str(e)}"
        ctx.send_text(f"❌ {error_message}", at_list)
        if ctx.logger:
            ctx.logger.error(f"handle_reminder 顶层错误: {e}", exc_info=True)
        return True

def handle_list_reminders(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """处理查看提醒命令（支持群聊和私聊）"""
    if not hasattr(ctx.robot, 'reminder_manager'):
        ctx.send_text("❌ 内部错误：提醒管理器未初始化。", ctx.msg.sender if ctx.is_group else "")
        return True

    reminders = ctx.robot.reminder_manager.list_reminders(ctx.msg.sender)
    # 在群聊中@用户
    at_list = ctx.msg.sender if ctx.is_group else ""

    if not reminders:
        ctx.send_text("您还没有设置任何提醒。", at_list)
        return True

    reply_parts = ["📝 您设置的提醒列表（包括私聊和群聊）：\n"]
    for i, r in enumerate(reminders):
        # 格式化星期几（如果存在）
        weekday_str = ""
        if r.get("weekday") is not None:
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            weekday_str = f" (每周{weekdays[r['weekday']]})" if 0 <= r['weekday'] <= 6 else ""

        # 格式化时间
        time_display = r['time_str']
        # 添加设置位置标记（群聊/私聊）
        scope_tag = ""
        if r.get('roomid'):
            # 尝试获取群聊名称，如果获取不到就用 roomid
            room_name = ctx.all_contacts.get(r['roomid']) or r['roomid'][:8]
            scope_tag = f"[群:{room_name}]"
        else:
            scope_tag = "[私聊]"
            
        if r['type'] == 'once':
            # 一次性提醒显示完整日期时间
            time_display = f"{scope_tag}{r['time_str']} (一次性)"
        elif r['type'] == 'daily':
            time_display = f"{scope_tag}每天 {r['time_str']}"
        elif r['type'] == 'weekly':
            if 0 <= r.get('weekday', -1) <= 6:
                time_display = f"{scope_tag}每周{weekdays[r['weekday']]} {r['time_str']}"
            else:
                time_display = f"{scope_tag}每周 {r['time_str']}"

        reply_parts.append(
            f"{i+1}. [ID: {r['id'][:6]}] {time_display}: {r['content']}"
        )
    ctx.send_text("\n".join(reply_parts), at_list)
        
    return True

def handle_delete_reminder(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    处理删除提醒命令（支持群聊和私聊）。
    检查消息是否包含"提醒"和"删"相关字眼，然后使用 AI 理解具体意图。
    """
    # 1. 获取用户输入的完整内容
    raw_text = ctx.msg.content.strip()

    # 2. 检查是否包含删除提醒的两个核心要素："提醒"和"删/删除/取消"
    #    Regex 已经保证了后者，这里只需检查前者
    if "提醒" not in raw_text:
        # 如果消息匹配了 "删" 但没有 "提醒"，说明不是删除提醒的意图，不处理
        return False # 返回 False，让命令路由器可以尝试匹配其他命令

    # 3. 检查 ReminderManager 是否存在
    if not hasattr(ctx.robot, 'reminder_manager'):
        # 这个检查需要保留，是内部依赖
        ctx.send_text("❌ 内部错误：提醒管理器未初始化。", ctx.msg.sender if ctx.is_group else "")
        return True # 确实是想处理，但内部错误，返回 True

    # 在群聊中@用户
    at_list = ctx.msg.sender if ctx.is_group else ""

    # --- 核心流程：直接使用 AI 分析 ---

    # 4. 获取用户的所有提醒作为 AI 的上下文
    reminders = ctx.robot.reminder_manager.list_reminders(ctx.msg.sender)
    if not reminders:
        # 如果用户没有任何提醒，直接告知
        ctx.send_text("您当前没有任何提醒可供删除。", at_list)
        return True

    # 将提醒列表转换为 JSON 字符串给 AI 参考
    try:
        reminders_json_str = json.dumps(reminders, ensure_ascii=False, indent=2)
    except Exception as e:
         ctx.send_text("❌ 内部错误：准备数据给 AI 时出错。", at_list)
         if ctx.logger: ctx.logger.error(f"序列化提醒列表失败: {e}", exc_info=True)
         return True

    # 5. 构造 AI Prompt (与之前相同，AI 需要能处理所有情况)
    # 注意：确保 prompt 中的 {{ 和 }} 转义正确
    sys_prompt = """
你是提醒删除助手。用户会提出删除提醒的请求。我会提供用户的**完整请求原文**，以及一个包含该用户所有当前提醒的 JSON 列表。

你的任务是：根据用户请求和提醒列表，判断用户的意图，并确定要删除哪些提醒。用户可能要求删除特定提醒（通过描述内容、时间、ID等），也可能要求删除所有提醒。

**必须严格**按照以下几种 JSON 格式之一返回结果：

1.  **删除特定提醒:** 如果你能明确匹配到一个或多个特定提醒，返回：
    ```json
    {{
      "action": "delete_specific",
      "ids": ["<full_reminder_id_1>", "<full_reminder_id_2>", ...]
    }}
    ```
    (`ids` 列表中包含所有匹配到的提醒的 **完整 ID**)

2.  **删除所有提醒:** 如果用户明确表达了删除所有/全部提醒的意图，返回：
    ```json
    {{
      "action": "delete_all"
    }}
    ```

3.  **需要澄清:** 如果用户描述模糊，匹配到多个可能的提醒，无法确定具体是哪个，返回：
    ```json
    {{
      "action": "clarify",
      "message": "抱歉，您的描述可能匹配多个提醒，请问您想删除哪一个？（建议使用 ID 精确删除）",
      "options": [ {{ "id": "id_prefix_1...", "description": "提醒1的简短描述(如: 周一 09:00 开会)" }}, ... ]
    }}
    ```
    (`message` 是给用户的提示，`options` 包含可能的选项及其简短描述和 ID 前缀)

4.  **未找到:** 如果在列表中找不到任何与用户描述匹配的提醒，返回：
    ```json
    {{
      "action": "not_found",
      "message": "抱歉，在您的提醒列表中没有找到与您描述匹配的提醒。"
    }}
    ```

5.  **错误:** 如果处理中遇到问题或无法理解请求，返回：
    ```json
    {{
      "action": "error",
      "message": "抱歉，处理您的删除请求时遇到问题。"
    }}
    ```

**重要:**
-   仔细分析用户的**完整请求原文**和提供的提醒列表 JSON 进行匹配。
-   用户请求中可能直接包含 ID，也需要你能识别并匹配。
-   匹配时要综合考虑内容、时间、类型（一次性/每日/每周）等信息。
-   如果返回 `delete_specific`，必须提供 **完整** 的 reminder ID。
-   **只输出 JSON 结构，不要包含任何额外的解释性文字。**

用户的提醒列表如下 (JSON 格式):
{reminders_list_json}

当前时间（供参考）: {current_datetime}
"""
    current_dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        # 将用户的自然语言请求和提醒列表JSON传入Prompt
        formatted_prompt = sys_prompt.format(
            reminders_list_json=reminders_json_str,
            current_datetime=current_dt_str
        )
    except KeyError as e:
         ctx.send_text("❌ 内部错误：构建 AI 请求时出错。", at_list)
         if ctx.logger: ctx.logger.error(f"格式化删除提醒 prompt 失败: {e}，可能是 sys_prompt 中的 {{}} 未正确转义", exc_info=True)
         return True


    # 6. 调用 AI (使用完整的用户原始输入)
    q_for_ai = f"请根据以下用户完整请求，分析需要删除哪个提醒：\n{raw_text}" # 使用 raw_text
    try:
        if not hasattr(ctx, 'chat') or not ctx.chat:
            raise ValueError("当前上下文中没有可用的AI模型")

        # 实现最多尝试3次解析AI回复的逻辑
        max_retries = 3
        retry_count = 0
        parsed_ai_response = None
        ai_parsing_success = False
        
        while retry_count < max_retries and not ai_parsing_success:
            # 如果是重试，更新提示信息
            if retry_count > 0:
                enhanced_prompt = sys_prompt + f"\n\n**重要提示:** 这是第{retry_count+1}次尝试。你之前的回复格式有误，无法被解析为有效的JSON。请确保你的回复仅包含有效的JSON对象，没有其他任何文字。"
                try:
                    formatted_prompt = enhanced_prompt.format(
                        reminders_list_json=reminders_json_str,
                        current_datetime=current_dt_str
                    )
                except Exception as e:
                    ctx.send_text("❌ 内部错误：构建重试请求时出错。", at_list)
                    if ctx.logger: ctx.logger.error(f"格式化重试 prompt 失败: {e}", exc_info=True)
                    return True
                    
                # 在重试时提供更明确的信息
                retry_q = f"请再次分析以下删除提醒请求，并返回严格的JSON格式(第{retry_count+1}次尝试):\n{raw_text}"
                q_for_ai = retry_q

            # 获取AI回答
            ai_response = ctx.chat.get_answer(q_for_ai, ctx.get_receiver(), system_prompt_override=formatted_prompt)

            # 7. 解析 AI 的 JSON 回复
            json_str = None
            json_match_obj = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match_obj:
                json_str = json_match_obj.group(0)
            else:
                json_str = ai_response

            try:
                parsed_ai_response = json.loads(json_str)
                if not isinstance(parsed_ai_response, dict) or "action" not in parsed_ai_response:
                    raise ValueError("AI 返回的 JSON 格式不符合预期（缺少 action 字段）")
                    
                # 如果能到这里，说明解析成功
                ai_parsing_success = True
                
            except (json.JSONDecodeError, ValueError) as e:
                # JSON解析失败
                retry_count += 1
                if ctx.logger: 
                    ctx.logger.warning(f"AI 删除提醒 JSON 解析失败(第{retry_count}次尝试): {ai_response}, 错误: {str(e)}")
                
                if retry_count >= max_retries:
                    # 达到最大重试次数，返回错误
                    ctx.send_text(f"❌ 抱歉，无法理解您的删除提醒请求。请尝试换一种方式表达，或使用提醒ID进行精确删除。", at_list)
                    if ctx.logger: ctx.logger.error(f"解析AI删除提醒回复失败，已达到最大重试次数({max_retries}): {ai_response}")
                    return True
                # 否则继续下一次循环重试

        # 8. 根据 AI 指令执行操作 (与之前相同)
        action = parsed_ai_response.get("action")

        if action == "delete_specific":
            reminder_ids_to_delete = parsed_ai_response.get("ids", [])
            if not reminder_ids_to_delete or not isinstance(reminder_ids_to_delete, list):
                 ctx.send_text("❌ AI 指示删除特定提醒，但未提供有效的 ID 列表。", at_list)
                 return True

            delete_results = []
            successful_deletes = 0
            deleted_descriptions = []

            for r_id in reminder_ids_to_delete:
                original_reminder = next((r for r in reminders if r['id'] == r_id), None)
                desc = f"ID:{r_id[:6]}..."
                if original_reminder:
                    desc = f"ID:{r_id[:6]}... 内容: \"{original_reminder['content'][:20]}...\""

                success, message = ctx.robot.reminder_manager.delete_reminder(ctx.msg.sender, r_id)
                delete_results.append({"id": r_id, "success": success, "message": message, "description": desc})
                if success:
                    successful_deletes += 1
                    deleted_descriptions.append(desc)

            if successful_deletes == len(reminder_ids_to_delete):
                reply_msg = f"✅ 已删除 {successful_deletes} 个提醒:\n" + "\n".join([f"- {d}" for d in deleted_descriptions])
            elif successful_deletes > 0:
                reply_msg = f"⚠️ 部分提醒删除完成 ({successful_deletes}/{len(reminder_ids_to_delete)}):\n"
                for res in delete_results:
                    status = "✅ 成功" if res["success"] else f"❌ 失败: {res['message']}"
                    reply_msg += f"- {res['description']}: {status}\n"
            else:
                reply_msg = f"❌ 未能删除 AI 指定的提醒。\n"
                for res in delete_results:
                     reply_msg += f"- {res['description']}: 失败原因: {res['message']}\n"

            ctx.send_text(reply_msg.strip(), at_list)

        elif action == "delete_all":
            success, message, count = ctx.robot.reminder_manager.delete_all_reminders(ctx.msg.sender)
            ctx.send_text(message, at_list)

        elif action in ["clarify", "not_found", "error"]:
            message_to_user = parsed_ai_response.get("message", "抱歉，我没能处理您的请求。")
            if action == "clarify" and "options" in parsed_ai_response:
                 options_text = "\n可能的选项：\n" + "\n".join([f"- ID: {opt.get('id', 'N/A')} ({opt.get('description', '无描述')})" for opt in parsed_ai_response["options"]])
                 message_to_user += options_text
            ctx.send_text(message_to_user, at_list)

        else:
            ctx.send_text("❌ AI 返回了无法理解的指令。", at_list)
            if ctx.logger: ctx.logger.error(f"AI 删除提醒返回未知 action: {action} - Response: {ai_response}")

        return True # AI 处理流程结束

    except Exception as e: # 捕获 AI 调用和处理过程中的其他顶层错误
        ctx.send_text(f"❌ 处理删除提醒时发生意外错误。", at_list)
        if ctx.logger:
            ctx.logger.error(f"handle_delete_reminder AI 部分顶层错误: {e}", exc_info=True)
        return True

def handle_weather_forecast(ctx: 'MessageContext', match: Optional[Match]) -> bool:
    """
    处理 "天气预报" 或 "预报" 命令

    匹配: 天气预报 [城市名] 或 预报 [城市名]
    """
    if not match:
        return False

    city_name = match.group(1).strip()
    if not city_name:
        ctx.send_text("🤔 请告诉我你想查询哪个城市的天气预报，例如：天气预报 北京")
        return True

    if ctx.logger:
        ctx.logger.info(f"天气预报查询指令匹配: 城市={city_name}")

    # --- 加载城市代码 ---
    city_codes: Dict[str, str] = {}
    city_code_path = os.path.join(os.path.dirname(__file__), '..', 'function', 'main_city.json') # 确保路径正确
    try:
        with open(city_code_path, 'r', encoding='utf-8') as f:
            city_codes = json.load(f)
    except FileNotFoundError:
        if ctx.logger:
            ctx.logger.error(f"城市代码文件未找到: {city_code_path}")
        ctx.send_text("⚠️ 抱歉，天气功能所需的城市列表文件丢失了。")
        return True
    except json.JSONDecodeError:
        if ctx.logger:
            ctx.logger.error(f"无法解析城市代码文件: {city_code_path}")
        ctx.send_text("⚠️ 抱歉，天气功能的城市列表文件格式错误。")
        return True
    except Exception as e:
         if ctx.logger:
            ctx.logger.error(f"加载城市代码时发生未知错误: {e}", exc_info=True)
         ctx.send_text("⚠️ 抱歉，加载城市代码时发生错误。")
         return True
    # --- 城市代码加载完毕 ---

    city_code = city_codes.get(city_name)

    if not city_code:
        # 尝试模糊匹配 (可选，如果需要)
        found = False
        for name, code in city_codes.items():
            if city_name in name: # 如果输入的名字是城市全名的一部分
                city_code = code
                city_name = name # 使用找到的完整城市名
                if ctx.logger:
                    ctx.logger.info(f"城市 '{match.group(1).strip()}' 未精确匹配，使用模糊匹配结果: {city_name} ({city_code})")
                found = True
                break
        if not found:
            ctx.send_text(f"😕 找不到城市 '{city_name}' 的天气信息，请检查城市名称是否正确。")
            return True

    # 获取天气信息 (包含预报)
    try:
        from function.func_weather import Weather
        weather_info = Weather(city_code).get_weather(include_forecast=True)  # 注意这里传入True
        ctx.send_text(weather_info)
    except Exception as e:
        if ctx.logger:
            ctx.logger.error(f"获取城市 {city_name}({city_code}) 天气预报时出错: {e}", exc_info=True)
        ctx.send_text(f"😥 获取 {city_name} 天气预报时遇到问题，请稍后再试。")

    return True
