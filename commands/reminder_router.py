import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from .context import MessageContext

REMINDER_ROUTER_HISTORY_LIMIT = 10


@dataclass
class ReminderDecision:
    action: str
    params: str = ""
    payload: Any = None
    message: str = ""
    success: bool = True


class ReminderRouter:
    """二级提醒路由器，单次调用AI即可产出最终执行计划。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__ + ".ReminderRouter")

    def route(self, ctx: MessageContext, original_text: str) -> Optional[ReminderDecision]:
        chat_model = getattr(ctx, "chat", None) or getattr(ctx.robot, "chat", None)
        if not chat_model:
            self.logger.error("提醒路由器：缺少可用的聊天模型。")
            return None

        reminder_manager = getattr(ctx.robot, "reminder_manager", None)
        reminders: list[Dict[str, Any]] = []
        reminders_available = False
        if reminder_manager:
            try:
                reminders = reminder_manager.list_reminders(ctx.msg.sender)
                reminders_available = True
            except Exception as exc:
                self.logger.error("提醒路由器：获取提醒列表失败: %s", exc, exc_info=True)
                reminders = []

        if reminders_available:
            reminders_section = json.dumps(reminders, ensure_ascii=False, indent=2)
            reminder_list_block = f"- 用户当前提醒列表：\n{reminders_section}\n"
            reminder_list_hint = (
                "提醒列表可用：是。你可以直接使用上面的提醒列表来匹配用户的删除请求。"
            )
        else:
            reminder_list_block = "- 该用户没有设置提醒。\n"
            reminder_list_hint = (
                "提醒列表不可用：当前无法获取提醒列表；请依赖用户描述，并在必要时提示对方补充信息。"
            )

        current_dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_text = (original_text or "").strip()

        system_prompt = (
            "你是提醒助手的决策引擎，需要在**一次调用**中完成意图识别与计划生成。\n"
            "请严格遵循以下说明：\n\n"
            "### 背景数据\n"
            f"- 当前准确时间：{current_dt_str}\n"
            f"{reminder_list_block}"
            f"- {reminder_list_hint}\n\n"
            "### 总体目标\n"
            "1. 根据用户原话判断动作：`create` / `list` / `delete`。\n"
            "2. 为动作生成可直接执行的结构化计划；如果信息不足或存在歧义，返回 `success=false` 并在 `message` 中解释。\n"
            "3. 输出的 JSON 必须可被机器解析，严禁附带多余说明。\n\n"
            "### 详细要求\n"
            "#### 1. 判定动作\n"
            "- 用户想新增提醒：`action=\"create\"`\n"
            "- 用户想查看提醒：`action=\"list\"`\n"
            "- 用户想删除或取消提醒：`action=\"delete\"`\n"
            "- 如用户表达多个意图，优先满足提醒相关需求；若实在无法判定，返回 `create` 并将 success 设为 false，提示需要澄清。\n\n"
            "#### 2. create 计划\n"
            "- `create.reminders` 必须是数组，每个元素都包含：\n"
            "  - `type`: \"once\" | \"daily\" | \"weekly\"\n"
            "  - `time`: once 使用 `YYYY-MM-DD HH:MM`；daily/weekly 使用 `HH:MM`，均需是未来时间。若用户只给出日期或时间，需要合理补全（优先使用当前年份、24 小时制）。\n"
            "  - `content`: 提醒内容，至少 2 个字符。\n"
            "  - `weekday`: 仅当 type=weekly 时填入整数 0-6（周一=0）。\n"
            "  - `extra`: 始终输出空对象 `{}`。\n"
            "- 用户一次提出多个提醒时需要全部拆分成数组元素。\n"
            "- 如果时间或内容无法确定，务必将 `success=false`，并在 `message` 里告诉用户需要补充的信息。\n\n"
            "#### 3. delete 计划\n"
            "- 如果无法访问提醒列表（reminders_available=false），尽量根据用户描述判断；若确实不能决定，返回 `success=false` 并说明原因。\n"
            "- 计划结构保持以下字段：\n"
            "  {\n"
            "    \"action\": \"delete_specific\" | \"delete_all\" | \"clarify\" | \"not_found\" | \"error\",\n"
            "    \"ids\": [...],              # delete_specific 时包含完整提醒 ID；否则忽略\n"
            "    \"message\": \"...\",         # 告诉用户的提示，必须是自然语言\n"
            "    \"options\": [               # 仅 clarify 时可用，给出候选项（id 前缀 + 简要描述）\n"
            "      {\"id\": \"id_prefix...\", \"description\": \"示例：周一 09:00 开会\"}\n"
            "    ]\n"
            "  }\n"
            "- `delete_all` 仅在用户明确提到“全部/所有提醒”时使用。\n"
            "- 若用户描述不足以匹配具体提醒，优先返回 `clarify` 并列出可能选项；若列表为空则用 `not_found`。\n\n"
            "#### 4. list 计划\n"
            "- 设置 `action=\"list\"`，无需额外字段。若需要提示用户（例如没有提醒），可填入 `message`。\n\n"
            "#### 5. 通用字段\n"
            "- `success`: 布尔值。只要计划能够直接执行就为 true；一旦需要用户补充信息或遇到错误，就置为 false。\n"
            "- `message`: 给用户的自然语言提示，可为空字符串。\n"
            "- 若 `success=false`，务必提供有帮助的 `message`，说明缺失信息或发生的问题。\n\n"
            "### 输出格式\n"
            "{\n"
            "  \"action\": \"create\" | \"list\" | \"delete\",\n"
            "  \"success\": true/false,\n"
            "  \"message\": \"...\",\n"
            "  \"create\": {\"reminders\": [...]},  # 仅当 action=create 时必须提供\n"
            "  \"delete\": {...}                   # 仅当 action=delete 时必须提供\n"
            "}\n"
            "- 字段顺序不限，但必须是有效 JSON。\n"
            "- 未使用的分支请完全省略（例如 action=list 时不要输出 create/delete）。\n\n"
            "### 参考示例（仅供理解，注意替换为真实数据）\n"
            "```json\n"
            "{\n"
            "  \"action\": \"create\",\n"
            "  \"success\": true,\n"
            "  \"message\": \"\",\n"
            "  \"create\": {\n"
            "    \"reminders\": [\n"
            "      {\"type\": \"once\", \"time\": \"2025-05-20 09:00\", \"content\": \"提交季度报告\", \"extra\": {}},\n"
            "      {\"type\": \"weekly\", \"time\": \"19:30\", \"content\": \"篮球训练\", \"weekday\": 2, \"extra\": {}}\n"
            "    ]\n"
            "  }\n"
            "}\n"
            "```\n"
            "```json\n"
            "{\n"
            "  \"action\": \"delete\",\n"
            "  \"success\": true,\n"
            "  \"message\": \"\",\n"
            "  \"delete\": {\n"
            "    \"action\": \"delete_specific\",\n"
            "    \"ids\": [\"d6f2ab341234\"],\n"
            "    \"message\": \"\",\n"
            "    \"options\": []\n"
            "  }\n"
            "}\n"
            "```\n"
            "```json\n"
            "{\n"
            "  \"action\": \"list\",\n"
            "  \"success\": true,\n"
            "  \"message\": \"\"\n"
            "}\n"
            "```\n"
            "始终只返回 JSON。\n"
        )

        user_prompt = f"用户原始请求：{user_text or '[空]'}"

        try:
            ai_response = chat_model.get_answer(
                user_prompt,
                wxid=ctx.get_receiver(),
                system_prompt_override=system_prompt,
                specific_max_history=REMINDER_ROUTER_HISTORY_LIMIT,
            )
            self.logger.debug("提醒路由器原始响应: %s", ai_response)
        except Exception as exc:
            self.logger.error("提醒路由器：调用模型失败: %s", exc, exc_info=True)
            return None

        decision_data = self._extract_json(ai_response)
        if decision_data is None:
            self.logger.warning("提醒路由器：无法解析模型输出，返回 None")
            return None

        action = (decision_data.get("action") or "").strip().lower()
        if action not in {"create", "list", "delete"}:
            self.logger.warning("提醒路由器：未知动作 %s，默认为 create。", action)
            action = "create"

        success = self._to_bool(decision_data.get("success", True))
        message = str(decision_data.get("message") or "").strip()
        payload: Any = None

        if action == "create":
            create_info = decision_data.get("create") or {}
            reminders_plan = create_info.get("reminders")
            if not isinstance(reminders_plan, list):
                reminders_plan = []
            normalized_text = user_text
            if normalized_text and not normalized_text.startswith("提醒我"):
                normalized_text = f"提醒我{normalized_text}"
            if not reminders_plan:
                success = False
                if not message:
                    message = "抱歉，我没有识别出可以设置的提醒。"
            payload = {
                "reminders": reminders_plan,
                "raw_text": original_text,
                "normalized_text": normalized_text,
            }

        elif action == "delete":
            delete_info = decision_data.get("delete") or {}
            delete_action = (delete_info.get("action") or "").strip()
            if not delete_action:
                success = False
                if not message:
                    message = "抱歉，我没能理解需要删除哪些提醒。"
            payload = {
                "parsed_ai_response": delete_info,
                "reminders": reminders,
                "raw_text": original_text,
                "normalized_text": user_text,
            }

        decision = ReminderDecision(
            action=action,
            params=original_text,
            payload=payload,
            message=message,
            success=success,
        )
        return decision

    def _extract_json(self, ai_response: str) -> Optional[Dict[str, Any]]:
        if not isinstance(ai_response, str):
            return None
        match = re.search(r"\{.*\}", ai_response, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            self.logger.error("提醒路由器：JSON 解析失败: %s", exc)
            return None

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y"}
        if isinstance(value, (int, float)):
            return value != 0
        return bool(value)


reminder_router = ReminderRouter()
