# ai_providers/ai_chatgpt.py
#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import base64
import os
from datetime import datetime
import time # 引入 time 模块

import httpx
from openai import APIConnectionError, APIError, AuthenticationError, OpenAI

# 引入 MessageSummary 类型提示 (如果需要更严格的类型检查)
try:
    from function.func_summary import MessageSummary
except ImportError:
    MessageSummary = object # Fallback if import fails or for simplified typing


class ChatGPT():
    def __init__(self, conf: dict, message_summary_instance: MessageSummary = None, bot_wxid: str = None) -> None:
        key = conf.get("key")
        api = conf.get("api")
        proxy = conf.get("proxy")
        prompt = conf.get("prompt")
        self.model = conf.get("model", "gpt-3.5-turbo")
        self.max_history_messages = conf.get("max_history_messages", 10) # 读取配置，默认10条
        self.LOG = logging.getLogger("ChatGPT")

        # 存储传入的实例和wxid 
        self.message_summary = message_summary_instance
        self.bot_wxid = bot_wxid
        if not self.message_summary:
             self.LOG.warning("MessageSummary 实例未提供给 ChatGPT，上下文功能将不可用！")
        if not self.bot_wxid:
             self.LOG.warning("bot_wxid 未提供给 ChatGPT，可能无法正确识别机器人自身消息！")

        if proxy:
            self.client = OpenAI(api_key=key, base_url=api, http_client=httpx.Client(proxy=proxy))
        else:
            self.client = OpenAI(api_key=key, base_url=api)

        self.system_content_msg = {"role": "system", "content": prompt if prompt else "You are a helpful assistant."} # 提供默认值
        self.support_vision = self.model == "gpt-4-vision-preview" or self.model == "gpt-4o" or "-vision" in self.model

    def __repr__(self):
        return 'ChatGPT'

    @staticmethod
    def value_check(conf: dict) -> bool:
        # 不再检查 prompt，因为可以没有默认 prompt
        if conf:
            # 也检查 max_history_messages (虽然有默认值) 
            if conf.get("key") and conf.get("api"): # and conf.get("max_history_messages") is not None: # 如果需要强制配置
                return True
        return False

    def get_answer(self, question: str, wxid: str, system_prompt_override=None, specific_max_history=None, tools=None, conversation_history=None):
        # 标准Function Call模式：使用传入的对话历史
        if conversation_history:
            api_messages = []
            # 添加系统提示
            effective_system_prompt = system_prompt_override if system_prompt_override else self.system_content_msg["content"]
            if effective_system_prompt:
                api_messages.append({"role": "system", "content": effective_system_prompt})
            # 添加当前时间提示
            now_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            api_messages.append({"role": "system", "content": f"Current time is: {now_time}"})
            # 使用传入的对话历史
            api_messages.extend(conversation_history)
        else:
            # 传统模式：从数据库获取历史记录
            api_messages = []

            # 1. 添加系统提示
            effective_system_prompt = system_prompt_override if system_prompt_override else self.system_content_msg["content"]
            if effective_system_prompt: # 确保有内容才添加
                 api_messages.append({"role": "system", "content": effective_system_prompt})

            # 添加当前时间提示（可选，但原代码有）
            now_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            time_mk = "Current time is: " # 或者其他合适的提示
            api_messages.append({"role": "system", "content": f"{time_mk}{now_time}"})


            # 2. 获取并格式化历史消息
            if self.message_summary and self.bot_wxid:
                history = self.message_summary.get_messages(wxid)

                # -限制历史消息数量
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
                    if content: # 避免添加空内容
                        if role == "user":
                            sender_name = msg.get('sender', '未知用户') # 获取发送者名字，如果不存在则使用默认值
                            formatted_content = f"{sender_name}: {content}" # 格式化内容，加入发送者名字
                            api_messages.append({"role": role, "content": formatted_content})
                        else: # 如果是助手（机器人自己）的消息，则不加名字
                             api_messages.append({"role": role, "content": content})
            else:
                self.LOG.warning(f"无法为 wxid={wxid} 获取历史记录，因为 message_summary 或 bot_wxid 未设置。")

            # 3. 添加当前用户问题
            if question: # 确保问题非空
                api_messages.append({"role": "user", "content": question})

        rsp = ""
        try:
            # 使用格式化后的 api_messages
            params = {
                "model": self.model,
                "messages": api_messages # 使用从数据库构建的消息列表
            }

            # 只有非o系列模型才设置temperature
            if not self.model.startswith("o"):
                params["temperature"] = 0.2

            # 如果提供了tools，添加到参数中
            if tools:
                params["tools"] = tools
                params["tool_choice"] = "auto"  # 让AI自动决定是否调用function

            ret = self.client.chat.completions.create(**params)

            # 检查是否有tool_calls
            if tools and ret.choices[0].message.tool_calls:
                # 返回tool_calls而不是普通文本
                return {
                    "tool_calls": [
                        {
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments
                            }
                        }
                        for tool_call in ret.choices[0].message.tool_calls
                    ]
                }
            else:
                # 普通文本响应
                rsp = ret.choices[0].message.content or ""
                rsp = rsp[2:] if rsp.startswith("\n\n") else rsp
                rsp = rsp.replace("\n\n", "\n")

        except AuthenticationError:
            self.LOG.error("OpenAI API 认证失败，请检查 API 密钥是否正确")
            rsp = "API认证失败"
        except APIConnectionError:
            self.LOG.error("无法连接到 OpenAI API，请检查网络连接")
            rsp = "网络连接错误"
        except APIError as e1:
            self.LOG.error(f"OpenAI API 返回了错误：{str(e1)}")
            rsp = f"API错误: {str(e1)}"
        except Exception as e0:
            self.LOG.error(f"发生未知错误：{str(e0)}")
            rsp = "发生未知错误"

        return rsp

    def encode_image_to_base64(self, image_path: str) -> str:
        """将图片文件转换为Base64编码

        Args:
            image_path (str): 图片文件路径

        Returns:
            str: Base64编码的图片数据
        """
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            self.LOG.error(f"图片编码失败: {str(e)}")
            return ""

    def get_image_description(self, image_path: str, prompt: str = "请详细描述这张图片中的内容") -> str:
        """使用GPT-4 Vision分析图片内容

        Args:
            image_path (str): 图片文件路径
            prompt (str, optional): 提示词. 默认为"请详细描述这张图片中的内容"

        Returns:
            str: 模型对图片的描述
        """
        if not self.support_vision:
            self.LOG.error(f"当前模型 {self.model} 不支持图片理解，请使用gpt-4-vision-preview或gpt-4o")
            return "当前模型不支持图片理解功能，请联系管理员配置支持视觉的模型（如gpt-4-vision-preview或gpt-4o）"

        if not os.path.exists(image_path):
            self.LOG.error(f"图片文件不存在: {image_path}")
            return "无法读取图片文件"

        try:
            base64_image = self.encode_image_to_base64(image_path)
            if not base64_image:
                return "图片编码失败"

            # 构建带有图片的消息 (这里不使用历史记录)
            messages = [
                {"role": "system", "content": "你是一个图片分析专家，擅长分析图片内容并提供详细描述。"}, # 可以使用 self.system_content_msg 如果适用
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]

            params = {
                "model": self.model,
                "messages": messages,
                "max_tokens": 1000
            }

            if not self.model.startswith("o"):
                params["temperature"] = 0.7

            response = self.client.chat.completions.create(**params)
            description = response.choices[0].message.content
            description = description[2:] if description.startswith("\n\n") else description
            description = description.replace("\n\n", "\n")

            return description

        except AuthenticationError:
            self.LOG.error("OpenAI API 认证失败，请检查 API 密钥是否正确")
            return "API认证失败，无法分析图片"
        except APIConnectionError:
            self.LOG.error("无法连接到 OpenAI API，请检查网络连接")
            return "网络连接错误，无法分析图片"
        except APIError as e1:
            self.LOG.error(f"OpenAI API 返回了错误：{str(e1)}")
            return f"API错误：{str(e1)}"
        except Exception as e0:
            self.LOG.error(f"分析图片时发生未知错误：{str(e0)}")
            return f"处理图片时出错：{str(e0)}"


if __name__ == "__main__":
    # --- 测试代码需要调整 ---
    # 需要模拟 MessageSummary 和提供 bot_wxid 才能测试
    print("请注意：直接运行此文件进行测试需要模拟 MessageSummary 并提供 bot_wxid。")
    pass # 避免直接运行时出错