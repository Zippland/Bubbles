# ai_providers/ai_deepseek.py
#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from copy import deepcopy
from datetime import datetime
import time # 引入 time 模块

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
        self.max_history_messages = conf.get("max_history_messages", 10) # 读取配置，默认10条
        self.strict_functions = bool(conf.get("function_call_strict", False))
        if self.strict_functions and conf.get("api") is None:
            # 严格模式需要 beta 端点
            api = "https://api.deepseek.com/beta"
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

    def get_answer(self, question: str, wxid: str, system_prompt_override=None, specific_max_history=None) -> str:
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


        # 2. 获取并格式化历史消息
        if self.message_summary and self.bot_wxid:
            history = self.message_summary.get_messages(wxid)

            # 限制历史消息数量
            # 优先使用传入的特定限制，如果没有则使用模型默认限制
            limit_to_use = specific_max_history if specific_max_history is not None else self.max_history_messages
            self.LOG.debug(f"获取历史记录 for {wxid}, 原始条数: {len(history)}, 使用限制: {limit_to_use}")
            
            if limit_to_use is not None and limit_to_use > 0:
                 history = history[-limit_to_use:] # 取最新的 N 条
            elif limit_to_use == 0: # 如果设置为0，则不包含历史
                 history = []
                 
            self.LOG.debug(f"应用限制后历史条数: {len(history)}")

            for msg in history:
                role = "assistant" if msg.get("sender_wxid") == self.bot_wxid else "user"
                content = msg.get('content', '')
                if content:
                    if role == "user":
                        sender_name = msg.get('sender', '未知用户') # 获取发送者名字
                        formatted_content = f"{sender_name}: {content}" # 格式化内容
                        api_messages.append({"role": role, "content": formatted_content})
                    else: # 助手消息
                         api_messages.append({"role": role, "content": content})
        else:
            self.LOG.warning(f"无法为 wxid={wxid} 获取历史记录，因为 message_summary 或 bot_wxid 未设置。")

        # 3. 添加当前用户问题
        if question:
            api_messages.append({"role": "user", "content": question})

        try:
            # 使用格式化后的 api_messages 
            response = self.client.chat.completions.create(
                model=self.model,
                messages=api_messages, # 使用构建的消息列表
                stream=False
            )
            final_response = response.choices[0].message.content


            return final_response

        except (APIConnectionError, APIError, AuthenticationError) as e1:
            self.LOG.error(f"DeepSeek API 返回了错误：{str(e1)}")
            return f"DeepSeek API 返回了错误：{str(e1)}"
        except Exception as e0:
            self.LOG.error(f"发生未知错误：{str(e0)}")
            return "抱歉，处理您的请求时出现了错误"

    def call_with_functions(self, messages, functions, wxid):
        """Invoke DeepSeek function-calling API."""
        try:
            tools = []
            for fn in functions:
                payload = deepcopy(fn)
                tool_entry = {
                    "type": "function",
                    "function": {
                        "name": payload.get("name"),
                        "description": payload.get("description", ""),
                        "parameters": payload.get("parameters", {}),
                    },
                }
                if self.strict_functions:
                    tool_entry["function"]["strict"] = True
                tools.append(tool_entry)

            params = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "stream": False,
            }

            response = self.client.chat.completions.create(**params)
            return response

        except (APIConnectionError, APIError, AuthenticationError) as exc:
            self.LOG.error(f"DeepSeek 函数调用失败: {exc}")
            raise
        except Exception as exc:  # pragma: no cover - 兜底保护
            self.LOG.error(f"调用 DeepSeek 函数接口时发生未知错误: {exc}", exc_info=True)
            raise


if __name__ == "__main__":
    # --- 测试代码需要调整 ---
    print("请注意：直接运行此文件进行测试需要模拟 MessageSummary 并提供 bot_wxid。")
    pass
