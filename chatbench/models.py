from __future__ import annotations

from datetime import date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 2
SENDER_IDS = ("buyer", "seller")
MESSAGE_TYPES = ("text", "image", "image_text")


def uid() -> str:
    return uuid4().hex


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_message(sender: str = "buyer", text: str = "", *, timestamp: str | None = None) -> dict:
    return {"id": uid(), "sender_id": sender, "text": text, "type": "text",
            "timestamp": timestamp, "asset_id": None, "manual_time": False, "locked": False,
            "source": "manual", "position": 0}


def normalize_positions(data: dict) -> None:
    for index, msg in enumerate(data["messages"]):
        msg["position"] = index


def new_conversation() -> dict:
    created = now_iso()
    data = {
        "schema_version": SCHEMA_VERSION, "conversation_id": uid(), "title": "法国手机充电器模拟对话",
        "country": "法国", "language": "法语", "timezone": "Asia/Shanghai",
        "conversation_date": date.today().isoformat(), "tone": "自然商务交流",
        "goal": "了解产品并讨论采购", "allow_details": True,
        "participants": {
            "buyer": {"name": "Camille Martin", "role": "采购经理", "company": "Atelier Lumière", "region": "法国", "style": "自然", "avatar_id": None,
                      "presence_mode": "hidden", "last_seen_at": None},
            "seller": {"name": "Alex Chen", "role": "销售代表", "company": "Example Supply", "region": "中国", "style": "专业友好", "avatar_id": None},
        },
        "product": {"name": "手机充电器", "brand": "", "model": "", "facts": "", "image_ids": []},
        "keywords": {"required": [], "forbidden": []},
        "time_rules": {"start": "09:00", "end": "16:30", "end_day_offset": 0,
                       "min_minutes": 5, "max_minutes": 30, "type_intervals": {},
                       "mode": "mixed", "preset": "正常回复"},
        "messages": [new_message("buyer" if i % 2 == 0 else "seller") for i in range(10)],
        "render_settings": {"width": 420, "style": "classic"}, "created_at": created, "updated_at": created,
    }
    normalize_positions(data)
    return data


def validate_conversation(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("不支持的聊天数据版本；需要 schema_version=2。")
    for field in ("conversation_id", "title", "country", "language", "timezone", "conversation_date", "participants", "product", "keywords", "time_rules", "messages"):
        if field not in data:
            raise ValueError(f"聊天数据缺少字段：{field}")
    settings = data.get("render_settings", {})
    if settings.get("style", "classic") not in ("classic", "wechat", "web"):
        raise ValueError("不支持的聊天界面样式。")
    if settings.get("tone", "warm") not in ("warm", "neutral"):
        raise ValueError("不支持的聊天色调。")
    pi = data.get("pi")
    if pi is not None and (not isinstance(pi, dict) or not isinstance(pi.get("fields"), dict)
                           or any(not isinstance(key, str) or not isinstance(value, str)
                                  for key, value in pi["fields"].items())):
        raise ValueError("PI 确认字段格式无效。")
    try:
        ZoneInfo(data["timezone"])
        date.fromisoformat(data["conversation_date"])
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("无效的日期或时区。") from exc
    buyer = data["participants"].get("buyer") if isinstance(data["participants"], dict) else None
    if not isinstance(buyer, dict):
        raise ValueError("买方资料无效。")
    presence_mode = buyer.get("presence_mode", "hidden")
    if presence_mode not in ("hidden", "online", "last_seen"):
        raise ValueError("买方在线状态无效。")
    if presence_mode == "last_seen":
        try:
            instant = datetime.fromisoformat(buyer["last_seen_at"])
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("最后上线时间必须包含时区。") from exc
    try:
        rules = data["time_rules"]
        time.fromisoformat(rules["start"])
        time.fromisoformat(rules["end"])
        if not 0 <= int(rules.get("end_day_offset", 0)) <= 7:
            raise ValueError()
        intervals = [rules] + list(rules.get("type_intervals", {}).values())
        if any(int(item["min_minutes"]) < 0 or int(item["max_minutes"]) < int(item["min_minutes"]) for item in intervals):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("时间规则无效。") from exc
    if not isinstance(data["messages"], list):
        raise ValueError("messages 必须为列表。")
    ids = set()
    for i, msg in enumerate(data["messages"], 1):
        if not isinstance(msg, dict) or not isinstance(msg.get("id"), str) or not msg["id"]:
            raise ValueError(f"第 {i} 条消息 ID 无效。")
        if msg["id"] in ids:
            raise ValueError("消息 ID 重复。")
        ids.add(msg["id"])
        if msg.get("position") != i - 1:
            raise ValueError(f"第 {i} 条消息的排序位置与列表顺序不一致。")
        if msg.get("sender_id") not in SENDER_IDS or msg.get("type") not in MESSAGE_TYPES:
            raise ValueError(f"第 {i} 条消息发送方或类型无效。")
        if msg.get("type") in ("image", "image_text") and not msg.get("asset_id"):
            raise ValueError(f"第 {i} 条图片消息缺少图片资源。")
        if msg.get("timestamp"):
            try:
                instant = datetime.fromisoformat(msg["timestamp"])
                if instant.tzinfo is None or instant.utcoffset() is None:
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise ValueError(f"第 {i} 条消息时间必须包含时区。") from exc
    return data


def keyword_warnings(data: dict) -> list[str]:
    joined = "\n".join(str(m.get("text", "")) for m in data["messages"]).casefold()
    required = [word for word in data["keywords"].get("required", []) if word.strip()]
    forbidden = [word for word in data["keywords"].get("forbidden", []) if word.strip()]
    warnings = [f"缺少必需关键词：{word}" for word in required if word.casefold() not in joined]
    warnings += [f"出现禁止关键词：{word}" for word in forbidden if word.casefold() in joined]
    return warnings
