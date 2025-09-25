"""Reminder related services for Function Call handlers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from function.func_reminder import ReminderManager


@dataclass
class ReminderServiceResult:
    success: bool
    messages: List[str]


_WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_TYPE_LABELS = {"once": "一次性", "daily": "每日", "weekly": "每周"}


def _format_schedule(data: Dict[str, Any]) -> str:
    reminder_type = data.get("type", "once")
    time_str = data.get("time", "?")

    if reminder_type == "once":
        return f"{time_str} (一次性)"
    if reminder_type == "daily":
        return f"每天 {time_str}"
    if reminder_type == "weekly":
        weekday = data.get("weekday")
        if isinstance(weekday, int) and 0 <= weekday < len(_WEEKDAY_LABELS):
            return f"每周{_WEEKDAY_LABELS[weekday]} {time_str}"
        return f"每周 {time_str}"
    return f"{time_str}"


def create_reminder(
    manager: ReminderManager,
    sender_wxid: str,
    data: Dict[str, Any],
    roomid: Optional[str]
) -> ReminderServiceResult:
    time_value = data["time"]
    if data.get("type") == "once":
        normalized_time = _normalize_once_time(time_value)
    else:
        normalized_time = time_value

    payload = {
        "type": data["type"],
        "time": normalized_time,
        "content": data["content"],
    }
    if data.get("weekday") is not None:
        payload["weekday"] = data["weekday"]

    success, info = manager.add_reminder(sender_wxid, payload, roomid=roomid)
    if not success:
        return ReminderServiceResult(success=False, messages=[f"❌ 设置提醒失败：{info}"])

    schedule = payload.copy()
    message = (
        "✅ 已为您设置{type_label}提醒\n"
        "时间: {schedule}\n"
        "内容: {content}"
    ).format(
        type_label=_TYPE_LABELS.get(payload["type"], ""),
        schedule=_format_schedule(payload),
        content=payload["content"],
    )
    return ReminderServiceResult(success=True, messages=[message])


def _normalize_once_time(time_str: str) -> str:
    raw = (time_str or "").strip()
    if not raw:
        return time_str

    parsed: Optional[datetime] = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        return time_str

    now = datetime.now()
    if parsed.year < now.year:
        try:
            candidate = parsed.replace(year=now.year)
        except ValueError:
            candidate = parsed
        if candidate <= now:
            try:
                candidate = candidate.replace(year=candidate.year + 1)
            except ValueError:
                candidate = parsed
        parsed = candidate

    return parsed.strftime("%Y-%m-%d %H:%M")


def list_reminders(
    manager: ReminderManager,
    sender_wxid: str,
    contacts: Dict[str, str]
) -> ReminderServiceResult:
    reminders = manager.list_reminders(sender_wxid)
    if not reminders:
        return ReminderServiceResult(success=True, messages=["您还没有设置任何提醒。"])

    lines: List[str] = ["📝 您设置的提醒列表（包括私聊和群聊）："]
    for idx, reminder in enumerate(reminders, start=1):
        schedule_display = _format_schedule({
            "type": reminder.get("type"),
            "time": reminder.get("time_str"),
            "weekday": reminder.get("weekday"),
        })
        if reminder.get("type") == "once":
            schedule_display = reminder.get("time_str", "?")
        scope = "[私聊]"
        roomid = reminder.get("roomid")
        if roomid:
            room_name = contacts.get(roomid) or roomid[:8]
            scope = f"[群:{room_name}]"
        lines.append(
            f"{idx}. [ID: {reminder.get('id', '')[:6]}] {scope}{schedule_display}: {reminder.get('content', '')}"
        )

    return ReminderServiceResult(success=True, messages=["\n".join(lines)])


def delete_reminder(manager: ReminderManager, sender_wxid: str, reminder_id: str) -> ReminderServiceResult:
    success, info = manager.delete_reminder(sender_wxid, reminder_id)
    if success:
        return ReminderServiceResult(success=True, messages=[f"✅ {info}"])
    return ReminderServiceResult(success=False, messages=[f"❌ {info}"])
