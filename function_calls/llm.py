"""LLM function-call orchestration utilities."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from commands.context import MessageContext

from .spec import FunctionResult, FunctionSpec

logger = logging.getLogger(__name__)


@dataclass
class LLMRunResult:
    """Result of the LLM routing pipeline."""

    handled: bool
    final_response: Optional[str] = None
    error: Optional[str] = None


class FunctionCallLLM:
    """Coordinate function-call capable models with router handlers."""

    def __init__(self, max_function_rounds: int = 5) -> None:
        self.logger = logger
        self.max_function_rounds = max_function_rounds

    def run(
        self,
        ctx: MessageContext,
        functions: Dict[str, FunctionSpec],
        executor: Callable[[FunctionSpec, Dict[str, Any]], FunctionResult],
        formatter: Callable[[FunctionResult], str],
    ) -> LLMRunResult:
        """Execute the function-call loop and return the final assistant response."""
        if not ctx.text:
            return LLMRunResult(handled=False)

        chat_model = getattr(ctx, "chat", None)
        if not chat_model and ctx.robot:
            chat_model = getattr(ctx.robot, "chat", None)

        if not chat_model:
            self.logger.error("无可用的AI模型")
            return LLMRunResult(handled=False, error="no_model")

        if not hasattr(chat_model, "call_with_functions"):
            self.logger.error("当前模型不支持函数调用接口，请配置支持 function calling 的模型")
            return LLMRunResult(handled=False, error="no_function_call_support")

        try:
            return self._run_native_loop(ctx, chat_model, functions, executor, formatter)
        except Exception as exc:  # pragma: no cover - safeguard
            self.logger.error(f"LLM 调用失败: {exc}")
            return LLMRunResult(handled=False, error=str(exc))

    # ---------------------------------------------------------------------
    # Native function-call workflow
    # ---------------------------------------------------------------------

    def _run_native_loop(
        self,
        ctx: MessageContext,
        chat_model: Any,
        functions: Dict[str, FunctionSpec],
        executor: Callable[[FunctionSpec, Dict[str, Any]], FunctionResult],
        formatter: Callable[[FunctionResult], str],
    ) -> LLMRunResult:
        openai_functions = self._build_functions_for_openai(functions)
        messages: List[Dict[str, Any]] = []

        system_prompt = (
            "You are an assistant that can call tools. "
            "When you invoke a function, wait for the tool response before replying to the user. "
            "Only deliver a final answer once you have enough information."
        )
        messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": ctx.text})

        for round_index in range(self.max_function_rounds):
            response = chat_model.call_with_functions(
                messages=messages,
                functions=openai_functions,
                wxid=ctx.get_receiver(),
            )

            if not getattr(response, "choices", None):
                self.logger.warning("函数调用返回空响应")
                return LLMRunResult(handled=False)

            message = response.choices[0].message
            assistant_entry = self._convert_assistant_message(message)
            messages.append(assistant_entry)

            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    if function_name not in functions:
                        self.logger.warning(f"模型请求未知函数: {function_name}")
                        tool_content = json.dumps(
                            {
                                "handled": False,
                                "messages": [f"Unknown function: {function_name}"],
                                "metadata": {"error": "unknown_function"},
                            },
                            ensure_ascii=False,
                        )
                    else:
                        try:
                            arguments = json.loads(tool_call.function.arguments or "{}")
                        except json.JSONDecodeError:
                            arguments = {}
                        spec = functions[function_name]
                        result = executor(spec, arguments)
                        tool_content = formatter(result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_content,
                        }
                    )
                continue

            # 没有工具调用，认为模型给出了最终回答
            final_content = message.content or ""
            return LLMRunResult(handled=True, final_response=final_content)

        self.logger.warning("达到最大函数调用轮数，未得到最终回答")
        return LLMRunResult(handled=False, error="max_rounds")

    @staticmethod
    def _convert_assistant_message(message: Any) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "role": "assistant",
            "content": message.content,
        }
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            entry["tool_calls"] = []
            for tool_call in tool_calls:
                entry["tool_calls"].append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                )
        return entry

    @staticmethod
    def _build_functions_for_openai(functions: Dict[str, FunctionSpec]) -> List[Dict[str, Any]]:
        openai_functions = []
        for spec in functions.values():
            openai_functions.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters_schema,
                }
            )
        return openai_functions

    def validate_arguments(self, arguments: Dict[str, Any], schema: Dict[str, Any]) -> bool:
        try:
            required_fields = schema.get("required", [])
            properties = schema.get("properties", {})

            for field in required_fields:
                if field not in arguments:
                    self.logger.warning(f"缺少必需参数: {field}")
                    return False

            for field, value in arguments.items():
                if field not in properties:
                    continue
                expected_type = properties[field].get("type")
                if expected_type == "string" and not isinstance(value, str):
                    self.logger.warning(f"参数 {field} 类型不正确，期望 string，得到 {type(value)}")
                    return False
                if expected_type == "integer" and not isinstance(value, int):
                    self.logger.warning(f"参数 {field} 类型不正确，期望 integer，得到 {type(value)}")
                    return False
                if expected_type == "number" and not isinstance(value, (int, float)):
                    self.logger.warning(f"参数 {field} 类型不正确，期望 number，得到 {type(value)}")
                    return False
            return True
        except Exception as exc:
            self.logger.error(f"参数验证失败: {exc}")
            return False
