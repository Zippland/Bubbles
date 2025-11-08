#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import time
from typing import List

import httpx
from openai import APIConnectionError, APIError, AuthenticationError, OpenAI

try:
    from function.func_summary import MessageSummary
except ImportError:  # pragma: no cover - fallback when typing
    MessageSummary = object


class Kimi:
    """Moonshot Kimi provider (兼容OpenAI SDK)"""

    def __init__(self, conf: dict, message_summary_instance: MessageSummary = None, bot_wxid: str = None) -> None:
        key = conf.get("key")
        api = conf.get("api", "https://api.moonshot.cn/v1")
        proxy = conf.get("proxy")
        prompt = conf.get("prompt")

        self.model = conf.get("model", "kimi-k2")
        self.max_history_messages = conf.get("max_history_messages", 30)
        self.show_reasoning = bool(conf.get("show_reasoning", False))
        self.LOG = logging.getLogger("Kimi")

        self.message_summary = message_summary_instance
        self.bot_wxid = bot_wxid

        if not self.message_summary:
            self.LOG.warning("MessageSummary 实例未提供给 Kimi，上下文功能将不可用！")
        if not self.bot_wxid:
            self.LOG.warning("bot_wxid 未提供给 Kimi，可能无法正确识别机器人自身消息！")

        if proxy:
            self.client = OpenAI(api_key=key, base_url=api, http_client=httpx.Client(proxy=proxy))
        else:
            self.client = OpenAI(api_key=key, base_url=api)

        self.system_content_msg = {
            "role": "system",
            "content": prompt or "你是 Kimi，一个由 Moonshot AI 打造的贴心助手。"
        }

    def __repr__(self) -> str:
        return "Kimi"

    @staticmethod
    def value_check(conf: dict) -> bool:
        if conf and conf.get("key"):
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
        api_messages = []

        effective_system_prompt = system_prompt_override if system_prompt_override else self.system_content_msg.get("content")
        if effective_system_prompt:
            api_messages.append({"role": "system", "content": effective_system_prompt})

        now_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        api_messages.append({"role": "system", "content": f"Current time is: {now_time}"})

        if self.message_summary and self.bot_wxid:
            history = self.message_summary.get_messages(wxid)

            limit_to_use = specific_max_history if specific_max_history is not None else self.max_history_messages
            try:
                limit_to_use = int(limit_to_use) if limit_to_use is not None else None
            except (TypeError, ValueError):
                limit_to_use = self.max_history_messages

            if limit_to_use is not None and limit_to_use > 0:
                history = history[-limit_to_use:]
            elif limit_to_use == 0:
                history = []

            for msg in history:
                role = "assistant" if msg.get("sender_wxid") == self.bot_wxid else "user"
                content = msg.get("content") or ""
                if not content:
                    continue
                if role == "user":
                    sender_name = msg.get("sender", "未知用户")
                    formatted_content = f"{sender_name}: {content}"
                    api_messages.append({"role": role, "content": formatted_content})
                else:
                    api_messages.append({"role": role, "content": content})
        else:
            self.LOG.debug(f"wxid={wxid} 无法加载历史记录（message_summary 或 bot_wxid 未设置）")

        if question:
            api_messages.append({"role": "user", "content": question})

        if tools and not tool_handler:
            self.LOG.warning("Kimi: 提供了 tools 但没有 tool_handler，忽略工具调用。")
            tools = None

        try:
            response_text, reasoning_text = self._execute_with_tools(
                api_messages=api_messages,
                tools=tools,
                tool_handler=tool_handler,
                tool_choice=tool_choice,
                tool_max_iterations=tool_max_iterations
            )

            if (
                self.show_reasoning
                and reasoning_text
                and isinstance(reasoning_text, str)
                and reasoning_text.strip()
            ):
                reasoning_output = reasoning_text.strip()
                final_answer = response_text.strip() if isinstance(response_text, str) else response_text
                return f"【思考过程】\n{reasoning_output}\n\n【最终回答】\n{final_answer}"

            return response_text

        except AuthenticationError:
            self.LOG.error("Kimi API 认证失败，请检查 API 密钥是否正确")
            return "Kimi API 认证失败，请检查配置。"
        except APIConnectionError:
            self.LOG.error("无法连接到 Kimi API，请检查网络或代理设置")
            return "无法连接到 Kimi 服务，请稍后再试。"
        except APIError as api_err:
            self.LOG.error(f"Kimi API 返回错误：{api_err}")
            return f"Kimi API 错误：{api_err}"
        except Exception as exc:
            self.LOG.error(f"Kimi 处理请求时出现未知错误：{exc}", exc_info=True)
            return "处理请求时出现未知错误，请稍后再试。"

    def _execute_with_tools(
        self,
        api_messages,
        tools=None,
        tool_handler=None,
        tool_choice=None,
        tool_max_iterations: int = 10
    ):
        iterations = 0
        params_base = {"model": self.model}
        runtime_tools = tools if tools and isinstance(tools, list) else None
        runtime_tool_choice = tool_choice
        reasoning_segments: List[str] = []

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

            reasoning_chunk = self._extract_reasoning_text(message)
            if reasoning_chunk:
                reasoning_segments.append(reasoning_chunk)

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
                        "content": "你已经达到允许的最大工具调用次数，请根据现有信息直接给出最终回答。"
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

            response_text = message.content if message and message.content else ""
            if response_text.startswith("\n\n"):
                response_text = response_text[2:]
            response_text = response_text.replace("\n\n", "\n")

            reasoning_text = "\n".join(seg for seg in reasoning_segments if seg).strip()
            return response_text, reasoning_text

    def _extract_reasoning_text(self, message) -> str:
        """Moonshot 在 ChatCompletionMessage 上挂载 reasoning_content 字段"""
        if not message:
            return ""
        raw_reasoning = getattr(message, "reasoning_content", None)
        if not raw_reasoning:
            return ""

        def _normalize_segment(segment) -> str:
            if isinstance(segment, str):
                return segment
            if isinstance(segment, dict):
                return segment.get("content") or segment.get("text") or ""
            if isinstance(segment, list):
                return "\n".join(filter(None, (_normalize_segment(item) for item in segment)))
            return str(segment) if segment is not None else ""

        if isinstance(raw_reasoning, list):
            segments = []
            for part in raw_reasoning:
                normalized = _normalize_segment(part)
                if normalized:
                    segments.append(normalized)
            return "\n".join(segments).strip()

        return _normalize_segment(raw_reasoning).strip()


__all__ = ["Kimi"]
