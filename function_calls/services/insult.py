"""Group insult helper utilities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from commands.context import MessageContext
from function.func_insult import generate_random_insult


@dataclass
class InsultResult:
    success: bool
    message: str


def build_insult(ctx: MessageContext, target_name: str) -> InsultResult:
    if not ctx.is_group:
        return InsultResult(success=True, message="❌ 骂人功能只支持群聊哦~")

    cleaned = target_name.strip()
    if not cleaned:
        return InsultResult(success=False, message="❌ 需要提供要骂的对象")

    actual_target = cleaned
    target_wxid: Optional[str] = None

    try:
        members = ctx.room_members
        if members:
            for wxid, name in members.items():
                if cleaned == name:
                    target_wxid = wxid
                    actual_target = name
                    break
            if target_wxid is None:
                for wxid, name in members.items():
                    if cleaned in name and wxid != ctx.robot_wxid:
                        target_wxid = wxid
                        actual_target = name
                        break
    except Exception as exc:
        if ctx.logger:
            ctx.logger.error(f"查找群成员信息时出错: {exc}")

    if target_wxid and target_wxid == ctx.robot_wxid:
        return InsultResult(success=True, message="😅 不行，我不能骂我自己。")

    insult_text = generate_random_insult(actual_target)
    return InsultResult(success=True, message=insult_text)
