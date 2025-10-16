import re
from typing import Optional, Match, Dict, Any
import json # 确保已导入json
from datetime import datetime # 确保已导入datetime
import os # 导入os模块用于文件路径操作

# 前向引用避免循环导入
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .context import MessageContext

DEFAULT_CHAT_HISTORY = 30

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
    raw_specific_max_history = getattr(ctx, 'specific_max_history', None)
    specific_max_history = None
    if raw_specific_max_history is not None:
        try:
            specific_max_history = int(raw_specific_max_history)
        except (TypeError, ValueError):
            specific_max_history = None
        if specific_max_history is not None:
            if specific_max_history < 10:
                specific_max_history = 10
            elif specific_max_history > 300:
                specific_max_history = 300
    if specific_max_history is None:
        specific_max_history = DEFAULT_CHAT_HISTORY
    setattr(ctx, 'specific_max_history', specific_max_history)
    if ctx.logger:
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
        tools = None
        tool_handler = None

        if ctx.robot and getattr(ctx.robot, 'message_summary', None):
            chat_id = ctx.get_receiver()
            message_summary = ctx.robot.message_summary

            history_lookup_tool = {
                "type": "function",
                "function": {
                    "name": "lookup_chat_history",
                    "description": (
                        "你目前只能看见最近的30条消息，所以不一定能设身处地地了解用户。"
                        "和人交流的过程中，掌握更多的上下文是非常重要的，这可以保证你的回答有温度、真实且有价值。"
                        "用户不会主动要求你去看上下文，但是你要自己判断需要看什么、看多少、看哪些上下文。"
                        "请你在回答之前，尽可能地通过查看历史记录来了解用户或事情的全貌，而如果需要查看历史记录消息，那么就请调用此函数。\n"
                        "调用时必须明确指定 mode（keywords / range / time），并按照以下说明提供参数：\n"
                        "1. mode=\"keywords\"：最常用的模式，用于对关键词进行模糊检索，用户对某些消息进行更深入的理解，在历史记录中找到这些内容的上下文。需要提供 `keywords` 数组（2-4 个与核心相关的词或短语），系统会自动按最新匹配段落返回，函数的返回值中 `segments` 列表包含格式化的 \"时间 昵称 内容\" 行。\n"
                        "2. mode=\"range\"：用于获取某个倒数的区间内的连续消息块，用于快速找到最近的 n 条消息，只有在对**最近的**记录进行观察时使用。需要提供 `start_offset` 与 `end_offset`（均需 >30，且 end_offset ≥ start_offset）。偏移基于最新消息的倒数编号，例如 31~120 表示排除当前可见的 30 条后，再向前取 90 条。\n"
                        "3. mode=\"time\"：次常用的模式，用于对某段时间内的消息进行检索，比如当提到昨晚、前天、昨天、今早上、上周、去年之类的具体时间的时候使用。需要提供 `start_time`、`end_time`（格式如 2025-05-01 08:00 或 2025-05-01 08:00:00），函数将返回该时间范围内的所有消息。若区间不符合用户需求，可再次调用调整时间。\n"
                        "函数随时可以多次调用并组合使用：例如先用 keywords 找锚点，再用 range/time 取更大上下文。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mode": {
                                "type": "string",
                                "description": "One of keywords, range, time.",
                                "enum": ["keywords", "range", "time"]
                            },
                            "keywords": {
                                "type": "array",
                                "description": "Keywords for fuzzy search when mode=keywords.",
                                "items": {"type": "string"}
                            },
                            "start_offset": {
                                "type": "integer",
                                "description": "Smaller offset counted from the latest message (>30) when mode=range."
                            },
                            "end_offset": {
                                "type": "integer",
                                "description": "Larger offset counted from the latest message (>30) when mode=range."
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start timestamp when mode=time (e.g., 2025-05-01 08:00[:00])."
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End timestamp when mode=time (e.g., 2025-05-01 12:00[:00])."
                            }
                        },
                        "additionalProperties": False
                    }
                }
            }

            def handle_tool_call(tool_name: str, arguments: Dict[str, Any]) -> str:
                try:
                    if tool_name != "lookup_chat_history":
                        return json.dumps({"error": f"Unknown tool '{tool_name}'"}, ensure_ascii=False)

                    mode = (arguments.get("mode") or "").strip().lower()
                    keywords = arguments.get("keywords")
                    start_offset = arguments.get("start_offset")
                    end_offset = arguments.get("end_offset")
                    start_time = arguments.get("start_time")
                    end_time = arguments.get("end_time")

                    inferred_mode = mode
                    if not inferred_mode:
                        if start_time and end_time:
                            inferred_mode = "time"
                        elif start_offset is not None and end_offset is not None:
                            inferred_mode = "range"
                        elif keywords:
                            inferred_mode = "keywords"
                        else:
                            inferred_mode = "keywords"

                    print(f"[lookup_chat_history] inferred_mode={inferred_mode}, raw_args={arguments}")
                    if ctx.logger:
                        ctx.logger.info(f"[lookup_chat_history] inferred_mode={inferred_mode}, raw_args={arguments}")

                    if inferred_mode == "keywords":
                        keywords = arguments.get("keywords", [])
                        if isinstance(keywords, str):
                            keywords = [keywords]
                        elif not isinstance(keywords, list):
                            keywords = []

                        cleaned_keywords = []
                        for kw in keywords:
                            if kw is None:
                                continue
                            kw_str = str(kw).strip()
                            if kw_str:
                                if len(kw_str) == 1 and not kw_str.isdigit():
                                    continue
                                cleaned_keywords.append(kw_str)

                        # 去重同时保持顺序
                        seen = set()
                        deduped_keywords = []
                        for kw in cleaned_keywords:
                            lower_kw = kw.lower()
                            if lower_kw not in seen:
                                seen.add(lower_kw)
                                deduped_keywords.append(kw)

                        if not deduped_keywords:
                            return json.dumps({"error": "No valid keywords provided.", "results": []}, ensure_ascii=False)

                        context_window = 5
                        max_results = 20

                        print(f"[search_chat_history] chat_id={chat_id}, keywords={deduped_keywords}, "
                              f"context_window={context_window}, max_results={max_results}")
                        if ctx.logger:
                            ctx.logger.info(
                                f"[search_chat_history] keywords={deduped_keywords}, "
                                f"context_window={context_window}, max_results={max_results}"
                            )

                        search_results = message_summary.search_messages_with_context(
                            chat_id=chat_id,
                            keywords=deduped_keywords,
                            context_window=context_window,
                            max_groups=max_results
                        )

                        segments = []
                        lines_seen = set()
                        for segment in search_results:
                            formatted = []
                            for line in segment.get("formatted_messages", []):
                                if line not in lines_seen:
                                    lines_seen.add(line)
                                    formatted.append(line)
                            if not formatted:
                                continue
                            segments.append({
                                "matched_keywords": segment.get("matched_keywords", []),
                                "messages": formatted
                            })

                        response_payload = {
                            "segments": segments,
                            "returned_groups": len(segments),
                            "keywords": deduped_keywords
                        }

                        print(f"[search_chat_history] returned_groups={len(segments)}")
                        if ctx.logger:
                            ctx.logger.info(f"[search_chat_history] returned_groups={len(segments)}")

                        if not segments:
                            response_payload["notice"] = "No messages matched the provided keywords."

                        return json.dumps(response_payload, ensure_ascii=False)

                    elif inferred_mode == "range":
                        if start_offset is None or end_offset is None:
                            return json.dumps({"error": "start_offset and end_offset are required."}, ensure_ascii=False)

                        try:
                            start_offset = int(start_offset)
                            end_offset = int(end_offset)
                        except (TypeError, ValueError):
                            return json.dumps({"error": "start_offset and end_offset must be integers."}, ensure_ascii=False)

                        if start_offset <= 30 or end_offset <= 30:
                            return json.dumps({"error": "Offsets must be greater than 30 to avoid visible messages."}, ensure_ascii=False)

                        if start_offset > end_offset:
                            start_offset, end_offset = end_offset, start_offset

                        print(f"[fetch_chat_history_range] chat_id={chat_id}, start_offset={start_offset}, "
                              f"end_offset={end_offset}")
                        if ctx.logger:
                            ctx.logger.info(
                                f"[fetch_chat_history_range] start_offset={start_offset}, "
                                f"end_offset={end_offset}"
                            )

                        range_result = message_summary.get_messages_by_reverse_range(
                            chat_id=chat_id,
                            start_offset=start_offset,
                            end_offset=end_offset
                        )

                        response_payload = {
                            "start_offset": range_result.get("start_offset"),
                            "end_offset": range_result.get("end_offset"),
                            "messages": range_result.get("messages", []),
                            "returned_count": range_result.get("returned_count", 0),
                            "total_messages": range_result.get("total_messages", 0)
                        }

                        print(f"[fetch_chat_history_range] returned_count={response_payload['returned_count']}")
                        if ctx.logger:
                            ctx.logger.info(
                                f"[fetch_chat_history_range] returned_count={response_payload['returned_count']}"
                            )

                        if response_payload["returned_count"] == 0:
                            response_payload["notice"] = "No messages available in the requested range."

                        return json.dumps(response_payload, ensure_ascii=False)

                    elif inferred_mode == "time":
                        if not start_time or not end_time:
                            return json.dumps({"error": "start_time and end_time are required."}, ensure_ascii=False)

                        print(f"[fetch_chat_history_time_window] chat_id={chat_id}, start_time={start_time}, end_time={end_time}")
                        if ctx.logger:
                            ctx.logger.info(
                                f"[fetch_chat_history_time_window] start_time={start_time}, end_time={end_time}"
                            )

                        time_lines = message_summary.get_messages_by_time_window(
                            chat_id=chat_id,
                            start_time=start_time,
                            end_time=end_time
                        )

                        response_payload = {
                            "start_time": start_time,
                            "end_time": end_time,
                            "messages": time_lines,
                            "returned_count": len(time_lines)
                        }

                        print(f"[fetch_chat_history_time_window] returned_count={response_payload['returned_count']}")
                        if ctx.logger:
                            ctx.logger.info(
                                f"[fetch_chat_history_time_window] returned_count={response_payload['returned_count']}"
                            )

                        if response_payload["returned_count"] == 0:
                            response_payload["notice"] = "No messages found within the requested time window."

                        return json.dumps(response_payload, ensure_ascii=False)

                    else:
                        return json.dumps({"error": f"Unsupported mode '{inferred_mode}'"}, ensure_ascii=False)

                except Exception as tool_exc:
                    if ctx.logger:
                        ctx.logger.error(f"历史搜索工具调用失败: {tool_exc}", exc_info=True)
                    return json.dumps(
                        {"error": f"History tool failed: {tool_exc.__class__.__name__}"},
                        ensure_ascii=False
                    )

            tools = [history_lookup_tool]
            tool_handler = handle_tool_call

        rsp = chat_model.get_answer(
            question=q_with_info, 
            wxid=ctx.get_receiver(),
            specific_max_history=specific_max_history,
            tools=tools,
            tool_handler=tool_handler,
            tool_max_iterations=10
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
    at_list = ctx.msg.sender if ctx.is_group else ""
    raw_text = ctx.msg.content.strip()

    parsed_reminders = []
    plan = getattr(ctx, "_reminder_create_plan", None)
    if hasattr(ctx, "_reminder_create_plan"):
        delattr(ctx, "_reminder_create_plan")

    if isinstance(plan, dict):
        parsed_reminders = plan.get("reminders", []) or []
        raw_text = plan.get("raw_text", raw_text)
    else:
        if not raw_text:
            ctx.send_text("请告诉我需要提醒什么内容和时间呀~ (例如：提醒我明天下午3点开会)", at_list)
            return True

        try:
            from .reminder_router import reminder_router
            decision = reminder_router.route(ctx, raw_text)
        except Exception as exc:
            if ctx.logger:
                ctx.logger.error(f"handle_reminder 路由解析失败: {exc}", exc_info=True)
            ctx.send_text("❌ 抱歉，暂时无法理解您的提醒请求。", at_list)
            return True

        if not decision or decision.action != "create":
            ctx.send_text("🤔 嗯... 我好像没太明白您想设置什么提醒，可以换种方式再说一次吗？", at_list)
            return True

        if not decision.success:
            ctx.send_text(decision.message or "❌ 抱歉，暂时无法理解您的提醒请求。", at_list)
            return True

        payload = decision.payload or {}
        parsed_reminders = payload.get("reminders", []) or []
        raw_text = payload.get("raw_text", raw_text)

    # 检查 ReminderManager 是否存在
    if not hasattr(ctx.robot, 'reminder_manager'):
        ctx.send_text("❌ 内部错误：提醒管理器未初始化。", at_list)
        if ctx.logger: ctx.logger.error("handle_reminder 无法访问 ctx.robot.reminder_manager")
        return True

    # 如果没有解析出任何提醒，告知用户
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
    """处理删除提醒命令（支持群聊和私聊），通过 AI 理解用户意图并执行操作。"""
    raw_text = ctx.msg.content.strip()

    reminder_manager = getattr(ctx.robot, 'reminder_manager', None)
    if not reminder_manager:
        ctx.send_text("❌ 内部错误：提醒管理器未初始化。", ctx.msg.sender if ctx.is_group else "")
        return True

    at_list = ctx.msg.sender if ctx.is_group else ""

    parsed_ai_response = None
    reminders = None

    plan = getattr(ctx, "_reminder_delete_plan", None)
    if hasattr(ctx, "_reminder_delete_plan"):
        delattr(ctx, "_reminder_delete_plan")

    if isinstance(plan, dict):
        parsed_ai_response = plan.get("parsed_ai_response")
        reminders = plan.get("reminders")
    else:
        try:
            from .reminder_router import reminder_router
            decision = reminder_router.route(ctx, raw_text)
        except Exception as exc:
            if ctx.logger:
                ctx.logger.error(f"handle_delete_reminder 路由解析失败: {exc}", exc_info=True)
            ctx.send_text("❌ 抱歉，无法理解您的删除提醒请求。请尝试换一种方式表达，或使用提醒ID进行精确删除。", at_list)
            return True

        if not decision or decision.action != "delete":
            ctx.send_text("❌ 抱歉，无法理解您的删除提醒请求。请尝试换一种方式表达，或使用提醒ID进行精确删除。", at_list)
            return True

        if not decision.success:
            ctx.send_text(decision.message or "❌ 抱歉，无法理解您的删除提醒请求。请尝试换一种方式表达，或使用提醒ID进行精确删除。", at_list)
            return True

        payload = decision.payload or {}
        parsed_ai_response = payload.get("parsed_ai_response")
        reminders = payload.get("reminders")

    if reminders is None:
        reminders = reminder_manager.list_reminders(ctx.msg.sender)

    if not reminders:
        ctx.send_text("您当前没有任何提醒可供删除。", at_list)
        return True

    if not isinstance(parsed_ai_response, dict) or "action" not in parsed_ai_response:
        ctx.send_text("❌ 抱歉，无法理解您的删除提醒请求。请尝试换一种方式表达，或使用提醒ID进行精确删除。", at_list)
        if ctx.logger:
            ctx.logger.error("handle_delete_reminder 未获得有效的 AI 删除指令: %s", parsed_ai_response)
        return True

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

            success, message = reminder_manager.delete_reminder(ctx.msg.sender, r_id)
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
        success, message, count = reminder_manager.delete_all_reminders(ctx.msg.sender)
        ctx.send_text(message, at_list)

    elif action in ["clarify", "not_found", "error"]:
        message_to_user = parsed_ai_response.get("message", "抱歉，我没能处理您的请求。")
        if action == "clarify" and "options" in parsed_ai_response:
            options_text = "\n可能的选项：\n" + "\n".join([f"- ID: {opt.get('id', 'N/A')} ({opt.get('description', '无描述')})" for opt in parsed_ai_response["options"]])
            message_to_user += options_text
        ctx.send_text(message_to_user, at_list)

    else:
        ctx.send_text("❌ AI 返回了无法理解的指令。", at_list)
        if ctx.logger:
            ctx.logger.error(f"AI 删除提醒返回未知 action: {action} - Parsed: {parsed_ai_response}")

    return True
