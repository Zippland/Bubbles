"""函数规格定义与相关数据结构"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from commands.context import MessageContext


@dataclass
class FunctionResult:
    """Standardized execution result returned by handlers."""

    handled: bool
    messages: list[str] = field(default_factory=list)
    at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def dispatch(self, ctx: MessageContext) -> None:
        """Send messages through the context when handled successfully."""
        if not self.handled:
            return

        for message in self.messages:
            ctx.send_text(message, self.at)

    def to_tool_content(self) -> str:
        """Serialize result for LLM tool messages."""
        payload = {
            "handled": self.handled,
            "messages": self.messages,
            "metadata": self.metadata or {},
        }
        return json.dumps(payload, ensure_ascii=False)


@dataclass
class FunctionSpec:
    """函数规格定义"""

    name: str
    description: str
    parameters_schema: Dict[str, Any]
    handler: Callable[[MessageContext, Any], FunctionResult]
    examples: list[str] = field(default_factory=list)
    scope: str = "both"  # group / private / both
    require_at: bool = False
    auth: Optional[str] = None  # 权限标签（可选）
