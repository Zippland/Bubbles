# ai_providers/ai_deepseek.py
#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from datetime import datetime
import time # 引入 time 模块
import json

import httpx
from openai import APIConnectionError, APIError, AuthenticationError, OpenAI

# 引入 MessageSummary 类型提示
try:
    from function.func_summary import MessageSummary
except ImportError:
    MessageSummary = object

class DeepSeek():
    def __init__(self, conf: dict, message_summary_instance: MessageSummary = None, bot_wxid: str = None) -> None:
        key = conf.get("key")
        api = conf.get("api", "https://api.deepseek.com")
        proxy = conf.get("proxy")
        prompt = conf.get("prompt")
        self.model = conf.get("model", "deepseek-chat")
        # 读取最大历史消息数配置 
        self.max_history_messages = conf.get("max_history_messages", 30) # 默认使用最近30条历史
        self.LOG = logging.getLogger("DeepSeek")

        # 存储传入的实例和wxid 
        self.message_summary = message_summary_instance
        self.bot_wxid = bot_wxid
        if not self.message_summary:
             self.LOG.warning("MessageSummary 实例未提供给 DeepSeek，上下文功能将不可用！")
        if not self.bot_wxid:
             self.LOG.warning("bot_wxid 未提供给 DeepSeek，可能无法正确识别机器人自身消息！")

        if proxy:
            self.client = OpenAI(api_key=key, base_url=api, http_client=httpx.Client(proxy=proxy))
        else:
            self.client = OpenAI(api_key=key, base_url=api)

        self.system_content_msg = {"role": "system", "content": prompt if prompt else "You are a helpful assistant."} # 提供默认值

    def __repr__(self):
        return 'DeepSeek'

    @staticmethod
    def value_check(conf: dict) -> bool:
        if conf:
            # 也检查 max_history_messages (虽然有默认值) 
            if conf.get("key"): # and conf.get("max_history_messages") is not None: # 如果需要强制配置
                return True
        return False

    def get_answer(
        self,
        question: str,
        wxid: str,
        system_prompt_override=None,
        specific_max_history=None,
        tools=None,
        tool_handler=None,
        tool_choice=None,
        tool_max_iterations: int = 10
    ) -> str:
        # 获取并格式化数据库历史记录 
        api_messages = []

        # 1. 添加系统提示
        effective_system_prompt = system_prompt_override if system_prompt_override else self.system_content_msg["content"]
        if effective_system_prompt:
             api_messages.append({"role": "system", "content": effective_system_prompt})

        # 添加当前时间提示 (可选)
        now_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        time_mk = "Current time is: "
        api_messages.append({"role": "system", "content": f"{time_mk}{now_time}"})


        # 2. 获取并格式化历史消息（使用上下文压缩）
        if self.message_summary and self.bot_wxid:
            limit_to_use = specific_max_history if specific_max_history is not None else self.max_history_messages
            try:
                limit_to_use = int(limit_to_use) if limit_to_use is not None else None
            except (TypeError, ValueError):
                limit_to_use = self.max_history_messages

            if limit_to_use == 0:
                history = []
                context_summary = None
            elif hasattr(self.message_summary, 'get_compressed_context'):
                history, context_summary = self.message_summary.get_compressed_context(
                    wxid, max_context_chars=8000, max_recent=limit_to_use
                )
            else:
                history = self.message_summary.get_messages(wxid)
                if limit_to_use and limit_to_use > 0:
                    history = history[-limit_to_use:]
                context_summary = None

            if context_summary:
                api_messages.append({"role": "system", "content": f"Earlier conversation context:\n{context_summary}"})

            for msg in history:
                role = "assistant" if msg.get("sender_wxid") == self.bot_wxid else "user"
                content = msg.get('content', '')
                if content:
                    if role == "user":
                        sender_name = msg.get('sender', '未知用户')
                        api_messages.append({"role": role, "content": f"{sender_name}: {content}"})
                    else:
                        api_messages.append({"role": role, "content": content})
        else:
            self.LOG.warning(f"无法为 wxid={wxid} 获取历史记录，因为 message_summary 或 bot_wxid 未设置。")

        # 3. 添加当前用户问题
        if question:
            api_messages.append({"role": "user", "content": question})

        if tools and not tool_handler:
            self.LOG.warning("tools 提供但未传入 tool_handler，忽略工具配置。")
            tools = None

        try:
            final_response = self._execute_with_tools(
                api_messages=api_messages,
                tools=tools,
                tool_handler=tool_handler,
                tool_choice=tool_choice,
                tool_max_iterations=tool_max_iterations
            )
            return final_response

        except (APIConnectionError, APIError, AuthenticationError) as e:
            self.LOG.error(f"DeepSeek API 调用失败: {e}")
            raise
        except Exception as e:
            self.LOG.error(f"DeepSeek 未知错误: {e}", exc_info=True)
            raise

    def _execute_with_tools(
        self,
        api_messages,
        tools=None,
        tool_handler=None,
        tool_choice=None,
        tool_max_iterations: int = 10
    ) -> str:
        iterations = 0
        params_base = {"model": self.model, "stream": False}

        runtime_tools = tools if tools and isinstance(tools, list) else None
        runtime_tool_choice = tool_choice

        while True:
            params = dict(params_base)
            params["messages"] = api_messages
            if runtime_tools:
                params["tools"] = runtime_tools
                if runtime_tool_choice:
                    params["tool_choice"] = runtime_tool_choice

            response = self.client.chat.completions.create(**params)
            choice = response.choices[0]
            message = choice.message
            finish_reason = choice.finish_reason

            if (
                runtime_tools
                and message
                and getattr(message, "tool_calls", None)
                and finish_reason == "tool_calls"
                and tool_handler
            ):
                iterations += 1
                api_messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": message.tool_calls
                })

                if tool_max_iterations is not None and iterations > max(tool_max_iterations, 0):
                    api_messages.append({
                        "role": "system",
                        "content": "你已经达到允许的最大搜索次数，请停止继续调用搜索工具，根据现有信息完成回答。"
                    })
                    runtime_tool_choice = "none"
                    continue

                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    raw_arguments = tool_call.function.arguments or "{}"
                    try:
                        parsed_arguments = json.loads(raw_arguments)
                    except json.JSONDecodeError:
                        parsed_arguments = {"_raw": raw_arguments}

                    try:
                        tool_output = tool_handler(tool_name, parsed_arguments)
                    except Exception as handler_exc:
                        self.LOG.error(f"工具 {tool_name} 执行失败: {handler_exc}", exc_info=True)
                        tool_output = json.dumps(
                            {"error": f"{tool_name} failed: {handler_exc.__class__.__name__}"},
                            ensure_ascii=False
                        )

                    if not isinstance(tool_output, str):
                        tool_output = json.dumps(tool_output, ensure_ascii=False)

                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_output
                    })

                runtime_tool_choice = None
                continue

            return message.content if message and message.content else ""


if __name__ == "__main__":
    # --- 测试代码需要调整 ---
    print("请注意：直接运行此文件进行测试需要模拟 MessageSummary 并提供 bot_wxid。")
    pass
