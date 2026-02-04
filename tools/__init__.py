"""
工具系统 —— 让 LLM 在 Agent 循环中自主调用工具。

每个 Tool 提供 OpenAI function-calling 格式的 schema 和一个同步执行函数。
ToolRegistry 汇总所有工具，生成 tools 列表和统一的 tool_handler。
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """LLM 可调用的工具。"""
    name: str
    description: str
    parameters: dict                          # JSON Schema
    handler: Callable[..., str] = None        # (ctx, **kwargs) -> str

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """收集工具，为 Agent 循环提供 tools + tool_handler。"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        logger.info(f"注册工具: {tool.name}")

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    @property
    def tools(self) -> Dict[str, Tool]:
        return dict(self._tools)

    def get_openai_tools(self) -> List[dict]:
        """返回所有工具的 OpenAI function-calling schema 列表。"""
        return [t.to_openai_schema() for t in self._tools.values()]

    def create_handler(self, ctx: Any) -> Callable[[str, dict], str]:
        """创建一个绑定了消息上下文的 tool_handler 函数。"""
        registry = self._tools

        def handler(tool_name: str, arguments: dict) -> str:
            tool = registry.get(tool_name)
            if not tool:
                return json.dumps(
                    {"error": f"Unknown tool: {tool_name}"},
                    ensure_ascii=False,
                )
            try:
                result = tool.handler(ctx, **arguments)
                if not isinstance(result, str):
                    result = json.dumps(result, ensure_ascii=False)
                return result
            except Exception as e:
                logger.error(f"工具 {tool_name} 执行失败: {e}", exc_info=True)
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        return handler


# ── 全局工具注册表 ──────────────────────────────────────────
tool_registry = ToolRegistry()
