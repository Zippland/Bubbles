# providers/base.py
"""LLM Provider 抽象基类定义"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json


@dataclass
class ToolCall:
    """工具调用数据类"""
    id: str
    name: str
    arguments: dict

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class LLMResponse:
    """LLM 响应数据类"""
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMProvider(ABC):
    """LLM Provider 抽象基类"""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """异步调用 LLM

        Args:
            messages: OpenAI 格式的消息列表
            tools: OpenAI 格式的工具定义列表

        Returns:
            LLMResponse: 包含响应内容和可能的工具调用
        """
        pass
