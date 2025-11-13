from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from commands.context import MessageContext


@dataclass
class ForwardRule:
    source_room_id: str
    target_room_ids: List[str]
    keywords: List[str]

    def matches(self, haystacks: Sequence[str]) -> bool:
        """Check whether any keyword is contained in the provided text pool."""
        if not self.keywords:
            return False

        for keyword in self.keywords:
            if not keyword:
                continue
            for item in haystacks:
                if keyword in item:
                    return True
        return False


class MessageForwarder:
    """Forward specific group messages to other groups based on keywords."""

    def __init__(self, robot: Any, config: Dict[str, Any], logger: Any) -> None:
        self.robot = robot
        self.logger = logger
        config = config if isinstance(config, dict) else {}
        self.enabled = bool(config.get("enable"))
        self.rules: List[ForwardRule] = (
            self._build_rules(config.get("rules", [])) if self.enabled else []
        )
        self.rules_by_room: Dict[str, List[ForwardRule]] = {}
        for rule in self.rules:
            self.rules_by_room.setdefault(rule.source_room_id, []).append(rule)

        if self.enabled and not self.rules:
            # 没有有效规则就视为未启用，避免无意义的检查
            self.enabled = False
            if self.logger:
                self.logger.warning("消息转发已启用，但未检测到有效规则，功能自动关闭。")

    def forward_if_needed(self, ctx: MessageContext) -> bool:
        """Forward the message when it matches a rule."""
        if (
            not self.enabled
            or not ctx.is_group
            or not ctx.msg
            or ctx.msg.from_self()
        ):
            return False

        room_id = ctx.msg.roomid
        candidate_rules = self.rules_by_room.get(room_id)
        if not candidate_rules:
            return False

        haystacks = self._build_haystacks(ctx)
        if not haystacks:
            return False

        payload = self._extract_forward_payload(ctx)
        if not payload:
            return False

        triggered = False
        for rule in candidate_rules:
            if not rule.matches(haystacks):
                continue
            triggered = True
            self._forward(rule, ctx, payload)

        return triggered

    def _build_rules(self, raw_rules: Sequence[Dict[str, Any]]) -> List[ForwardRule]:
        rules: List[ForwardRule] = []

        for raw in raw_rules or []:
            if not isinstance(raw, dict):
                continue

            source = raw.get("source_room_id") or raw.get("source")
            targets = raw.get("target_room_ids") or raw.get("target_room_id") or raw.get(
                "target"
            )
            keywords = raw.get("keywords") or raw.get("keyword")

            normalized_targets = self._normalize_str_list(targets)
            normalized_keywords = self._normalize_str_list(keywords)

            if not source or not normalized_targets or not normalized_keywords:
                if self.logger:
                    self.logger.warning(
                        f"忽略无效的消息转发配置: source={source}, targets={targets}, keywords={keywords}"
                    )
                continue

            rules.append(
                ForwardRule(
                    source_room_id=str(source).strip(),
                    target_room_ids=normalized_targets,
                    keywords=normalized_keywords,
                )
            )

        return rules

    @staticmethod
    def _normalize_str_list(value: Any) -> List[str]:
        if isinstance(value, str):
            cleaned = value.strip()
            return [cleaned] if cleaned else []
        if isinstance(value, (list, tuple, set)):
            result = []
            for item in value:
                if not isinstance(item, str):
                    continue
                cleaned = item.strip()
                if cleaned:
                    result.append(cleaned)
            return result
        return []

    def _build_haystacks(self, ctx: MessageContext) -> List[str]:
        haystacks: List[str] = []
        raw_content = getattr(ctx.msg, "content", None)
        if isinstance(raw_content, str) and raw_content:
            haystacks.append(raw_content)
        if isinstance(ctx.text, str) and ctx.text:
            haystacks.append(ctx.text)
        return haystacks

    def _extract_forward_payload(self, ctx: MessageContext) -> str:
        msg_type = getattr(ctx.msg, "type", None)
        if msg_type == 49 and ctx.text:
            return ctx.text
        raw_content = getattr(ctx.msg, "content", "")
        if isinstance(raw_content, str) and raw_content:
            return raw_content
        if isinstance(ctx.text, str):
            return ctx.text
        return ""

    def _forward(self, rule: ForwardRule, ctx: MessageContext, payload: str) -> None:
        sender_name = getattr(ctx, "sender_name", ctx.msg.sender)
        group_alias = self._resolve_group_alias(rule.source_room_id)
        forward_message = (
            f"【转发自 {group_alias}｜{sender_name}】\n"
            f"{payload}"
        )

        for target_id in rule.target_room_ids:
            try:
                self.robot.sendTextMsg(forward_message, target_id)
                if self.logger:
                    self.logger.info(
                        f"已将群 {rule.source_room_id} 的关键词消息转发至 {target_id}"
                    )
            except Exception as exc:
                if self.logger:
                    self.logger.error(
                        f"转发消息到 {target_id} 失败: {exc}",
                        exc_info=True,
                    )

    def _resolve_group_alias(self, room_id: str) -> str:
        contacts = getattr(self.robot, "allContacts", {}) or {}
        alias = contacts.get(room_id)
        return alias or room_id
