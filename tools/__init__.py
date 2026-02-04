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
    status_text: str = ""                     # 执行前发给用户的状态提示，空则不发

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
        """创建一个绑定了消息上下文的 tool_handler 函数。

        执行工具前，如果该工具配置了 status_text，会先给用户发一条状态提示，
        让用户知道"机器人在干什么"（类似 OpenClaw/OpenCode 的中间过程输出）。
        """
        registry = self._tools

        def _send_status(tool: 'Tool', arguments: dict) -> None:
            """发送工具执行状态消息给用户。"""
            if not tool.status_text:
                return
            try:
                # 对搜索类工具，把查询关键词带上
                status = tool.status_text
                if tool.name == "web_search" and arguments.get("query"):
                    status = f"{status}{arguments['query']}"
                elif tool.name == "lookup_chat_history" and arguments.get("keywords"):
                    kw_str = "、".join(str(k) for k in arguments["keywords"][:3])
                    status = f"{status}{kw_str}"

                ctx.send_text(status, record_message=False)
            except Exception:
                pass  # 状态提示失败不影响工具执行

        def handler(tool_name: str, arguments: dict) -> str:
            tool = registry.get(tool_name)
            if not tool:
                return json.dumps(
                    {"error": f"Unknown tool: {tool_name}"},
                    ensure_ascii=False,
                )

            _send_status(tool, arguments)

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
