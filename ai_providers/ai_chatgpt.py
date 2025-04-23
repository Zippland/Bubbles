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
    # ---- 修改 __init__ ----
    def __init__(self, conf: dict, message_summary_instance: MessageSummary = None, bot_wxid: str = None) -> None:
        key = conf.get("key")
        api = conf.get("api")
        proxy = conf.get("proxy")
        prompt = conf.get("prompt")
        self.model = conf.get("model", "gpt-3.5-turbo")
        # ---- 新增：读取最大历史消息数配置 ----
        self.max_history_messages = conf.get("max_history_messages", 10) # 读取配置，默认10条
        # ---- 新增结束 ----
        self.LOG = logging.getLogger("ChatGPT")

        # ---- 存储传入的实例和wxid ----
        self.message_summary = message_summary_instance
        self.bot_wxid = bot_wxid
        if not self.message_summary:
             self.LOG.warning("MessageSummary 实例未提供给 ChatGPT，上下文功能将不可用！")
        if not self.bot_wxid:
             self.LOG.warning("bot_wxid 未提供给 ChatGPT，可能无法正确识别机器人自身消息！")
        # ---- 存储结束 ----

        if proxy:
            self.client = OpenAI(api_key=key, base_url=api, http_client=httpx.Client(proxy=proxy))
        else:
            self.client = OpenAI(api_key=key, base_url=api)

        # ---- 移除 self.conversation_list ----
        # self.conversation_list = {}
        # ---- 移除结束 ----

        self.system_content_msg = {"role": "system", "content": prompt if prompt else "You are a helpful assistant."} # 提供默认值
        self.support_vision = self.model == "gpt-4-vision-preview" or self.model == "gpt-4o" or "-vision" in self.model
    # ---- __init__ 修改结束 ----

    def __repr__(self):
        return 'ChatGPT'

    @staticmethod
    def value_check(conf: dict) -> bool:
        # 不再检查 prompt，因为可以没有默认 prompt
        if conf:
            # ---- 修改：也检查 max_history_messages (虽然有默认值) ----
            if conf.get("key") and conf.get("api"): # and conf.get("max_history_messages") is not None: # 如果需要强制配置
                return True
        return False

    # ---- 修改 get_answer ----
    def get_answer(self, question: str, wxid: str, system_prompt_override=None) -> str:
        # ---- 移除 #清除对话 逻辑 ----
        # ... (代码已移除) ...
        # ---- 移除结束 ----

        # ---- 获取并格式化数据库历史记录 ----
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

            # ---- 新增：限制历史消息数量 ----
            if self.max_history_messages is not None and self.max_history_messages > 0:
                 history = history[-self.max_history_messages:] # 取最新的 N 条
            elif self.max_history_messages == 0: # 如果设置为0，则不包含历史
                 history = []
            # ---- 新增结束 ----

            for msg in history:
                role = "assistant" if msg.get("sender_wxid") == self.bot_wxid else "user"
                formatted_content = msg.get('content', '')
                if formatted_content: # 避免添加空内容
                    api_messages.append({"role": role, "content": formatted_content})
        else:
            self.LOG.warning(f"无法为 wxid={wxid} 获取历史记录，因为 message_summary 或 bot_wxid 未设置。")

        # 3. 添加当前用户问题
        if question: # 确保问题非空
            api_messages.append({"role": "user", "content": question})
        # ---- 获取和格式化结束 ----

        rsp = ""
        try:
            # ---- 使用格式化后的 api_messages ----
            params = {
                "model": self.model,
                "messages": api_messages # 使用从数据库构建的消息列表
            }

            # 只有非o系列模型才设置temperature
            if not self.model.startswith("o"):
                params["temperature"] = 0.2

            ret = self.client.chat.completions.create(**params)
            rsp = ret.choices[0].message.content
            rsp = rsp[2:] if rsp.startswith("\n\n") else rsp
            rsp = rsp.replace("\n\n", "\n")

            # ---- 移除 updateMessage 调用 ----
            # ... (代码已移除) ...
            # ---- 移除结束 ----

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
    # ---- get_answer 修改结束 ----

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

    # ---- 移除 updateMessage ----
    # ... (代码已移除) ...
    # ---- 移除结束 ----


if __name__ == "__main__":
    # --- 测试代码需要调整 ---
    # 需要模拟 MessageSummary 和提供 bot_wxid 才能测试
    print("请注意：直接运行此文件进行测试需要模拟 MessageSummary 并提供 bot_wxid。")
    pass # 避免直接运行时出错