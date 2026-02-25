# agent/tools/base.py
"""Tool 抽象基类定义"""

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.context import AgentContext


class Tool(ABC):
    """工具抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """OpenAI 格式的参数 JSON Schema"""
        ...

    @abstractmethod
    async def execute(self, ctx: "AgentContext", **kwargs) -> str:
        """异步执行工具

        Args:
            ctx: Agent 上下文
            **kwargs: 工具参数

        Returns:
            JSON 格式的执行结果
        """
        ...

    @property
    def status_text(self) -> str | None:
        """执行时显示的状态文本，None 表示不显示"""
        return None

    @property
    def status_arg(self) -> str | None:
        """用于状态文本的参数名"""
        return None

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI 工具格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
