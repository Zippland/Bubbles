import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .context import MessageContext

REMINDER_ROUTER_HISTORY_LIMIT = 10


@dataclass
class ReminderDecision:
    action: str
    params: str = ""


class ReminderRouter:
    """二级提醒路由器，用于在提醒场景下判定具体操作"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__ + ".ReminderRouter")

    def _build_prompt(self) -> str:
        return (
            "你是提醒助手的路由器。根据用户关于提醒的说法，判断应该执行哪个操作，并返回 JSON。\n\n"
            "### 可执行的操作：\n"
            "- create：创建新的提醒，需要从用户话语中提取完整的提醒内容（包括时间、人称、事项等）。\n"
            "- list：查询当前用户的所有提醒，当用户想要查看、看看、列出、有哪些提醒时使用。\n"
            "- delete：删除提醒，当用户想取消、删除、移除某个提醒时使用。需要根据用户给出的描述、关键字或者编号帮助定位哪条提醒。\n\n"
            "### 返回格式：\n"
            "{\n"
            '  "action": "create" | "list" | "delete",\n'
            '  "content": "从用户话语中提取或保留的关键信息（删除或新增时必填）"\n'
            "}\n\n"
            "注意：只返回 JSON，不要包含多余文字。若无法识别，返回 create 并把原句放进 content。"
        )

    def route(self, ctx: MessageContext, original_text: str) -> Optional[ReminderDecision]:
        chat_model = getattr(ctx, "chat", None) or getattr(ctx.robot, "chat", None)
        if not chat_model:
            self.logger.error("提醒路由器：缺少可用的聊天模型。")
            return None

        prompt = self._build_prompt()
        user_input = f"用户关于提醒的输入：{original_text}"

        try:
            ai_response = chat_model.get_answer(
                user_input,
                wxid=ctx.get_receiver(),
                system_prompt_override=prompt,
                specific_max_history=REMINDER_ROUTER_HISTORY_LIMIT,
            )
            self.logger.debug("提醒路由器原始响应: %s", ai_response)

            json_match = json.loads(json_response(ai_response))
            action = json_match.get("action", "").strip().lower()
            content = json_match.get("content", "").strip()
            if action not in {"create", "list", "delete"}:
                self.logger.warning("提醒路由器：未知动作 %s，默认为 create。", action)
                action = "create"
            return ReminderDecision(action=action, params=content)
        except Exception as exc:
            self.logger.error("提醒路由器解析失败: %s", exc, exc_info=True)
            return None


def json_response(raw: str) -> str:
    """从模型返回的文本中提取 JSON。"""
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return raw[start:end]
    except ValueError:
        return "{}"


reminder_router = ReminderRouter()
