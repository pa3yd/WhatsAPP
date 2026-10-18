from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def _bounds(data: dict) -> tuple[datetime, datetime]:
    rules = data["time_rules"]
    zone = ZoneInfo(data["timezone"])
    day = datetime.fromisoformat(data["conversation_date"]).date()
    start = datetime.combine(day, time.fromisoformat(rules["start"]), zone)
    offset = int(rules.get("end_day_offset", 0))
    if offset < 0 or offset > 7:
        raise ValueError("结束日期偏移只能为 0–7 天。")
    end = datetime.combine(day + timedelta(days=offset), time.fromisoformat(rules["end"]), zone)
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间；跨日请设置结束日期偏移。")
    if not _valid_local(start, zone) or not _valid_local(end, zone):
        raise ValueError("开始或结束时间处于夏令时不存在的本地时刻。")
    return start, end


def _valid_local(value: datetime, zone: ZoneInfo) -> bool:
    # Detect nonexistent local times at DST transitions.
    utc = value.astimezone(ZoneInfo("UTC"))
    return utc.astimezone(zone).replace(tzinfo=None) == value.replace(tzinfo=None)


def parse_manual(day, clock, timezone: str) -> str:
    zone = ZoneInfo(timezone)
    value = datetime.combine(day, clock, zone)
    if not _valid_local(value, zone):
        raise ValueError("该本地时间因夏令时切换而不存在，请选择另一时间。")
    return value.isoformat(timespec="minutes")


def _interval(rules: dict, message: dict) -> tuple[int, int]:
    override = rules.get("type_intervals", {}).get(message["type"], {})
    minimum = int(override.get("min_minutes", rules["min_minutes"]))
    maximum = int(override.get("max_minutes", rules["max_minutes"]))
    if minimum < 0 or maximum < minimum:
        raise ValueError(f"{message['type']} 的回复间隔范围无效。")
    return minimum, maximum


def _allocate(bounds: list[tuple[int, int]], available: int, *, exact: bool) -> list[int]:
    """Allocate integer minute gaps, respecting each message type's bounds."""
    minimum = sum(low for low, _ in bounds)
    maximum = sum(high for _, high in bounds)
    if available < minimum or (exact and available > maximum):
        raise ValueError("固定时间或时间窗口无法满足消息类型的间隔规则。")
    target = sum((low + high) // 2 for low, high in bounds)
    total = available if exact else min(available, target)
    gaps = [low for low, _ in bounds]
    remaining = total - minimum
    while remaining:
        changed = False
        for i, (_, high) in enumerate(bounds):
            if gaps[i] < high and remaining:
                gaps[i] += 1
                remaining -= 1
                changed = True
        if not changed:
            break
    return gaps


def assign_times(data: dict, *, recalculate_manual: bool = False) -> None:
    """Assign unlocked automatic times within fixed anchors, atomically on success."""
    messages = data["messages"]
    if not messages:
        return
    start, end = _bounds(data)
    rules = data["time_rules"]
    intervals = [None] + [_interval(rules, msg) for msg in messages[1:]]
    if rules.get("mode") == "manual" and not recalculate_manual:
        raise ValueError("全部手动模式不会自动分配时间。")
    zone = ZoneInfo(data["timezone"])
    anchors: dict[int, datetime] = {}
    if not recalculate_manual:
        for i, msg in enumerate(messages):
            if msg.get("manual_time") or msg.get("locked"):
                if not msg.get("timestamp"):
                    raise ValueError(f"第 {i + 1} 条固定消息没有时间。")
                anchors[i] = datetime.fromisoformat(msg["timestamp"]).astimezone(zone)
    for i, point in anchors.items():
        if not start <= point <= end:
            raise ValueError(f"第 {i + 1} 条固定时间超出范围。")
    if any(anchors[a] >= anchors[b] for a, b in zip(sorted(anchors), sorted(anchors)[1:])):
        raise ValueError("人工固定时间与消息顺序冲突。")
    result = [None] * len(messages)
    for i, point in anchors.items():
        result[i] = point
    ordered = sorted(anchors)
    if ordered:
        first = ordered[0]
        lead_room = int((anchors[first] - start).total_seconds() / 60)
        lead_gaps = _allocate(intervals[1:first+1], lead_room, exact=False)
        for i in range(first - 1, -1, -1):
            result[i] = result[i+1] - timedelta(minutes=lead_gaps[i])
        for left, right in zip(ordered, ordered[1:]):
            available = int((anchors[right] - anchors[left]).total_seconds() / 60)
            gaps = _allocate(intervals[left+1:right+1], available, exact=True)
            for i in range(left + 1, right):
                result[i] = result[i-1] + timedelta(minutes=gaps[i-left-1])
        last = ordered[-1]
        tail_room = int((end - anchors[last]).total_seconds() / 60)
        tail_gaps = _allocate(intervals[last+1:], tail_room, exact=False)
        for i in range(last + 1, len(messages)):
            result[i] = result[i-1] + timedelta(minutes=tail_gaps[i-last-1])
    else:
        available = int((end - start).total_seconds() / 60)
        gaps = _allocate(intervals[1:], available, exact=False)
        result[0] = start
        for i in range(1, len(messages)):
            result[i] = result[i-1] + timedelta(minutes=gaps[i-1])
    for i, point in enumerate(result):
        if point is None or not start <= point <= end or not _valid_local(point, zone):
            raise ValueError("时间安排超出范围或遇到夏令时无效时间。")
        if i:
            low, high = intervals[i]
            gap = (point - result[i-1]).total_seconds() / 60
            if not low <= gap <= high:
                raise ValueError("无法满足该消息类型的回复间隔。")
    for msg, point in zip(messages, result):
        if not (msg.get("manual_time") or msg.get("locked")) or recalculate_manual:
            msg["timestamp"] = point.isoformat(timespec="minutes")
            msg["manual_time"] = False


def timeline_warnings(data: dict) -> list[str]:
    warnings = []
    previous = None
    rules = data["time_rules"]
    for i, msg in enumerate(data["messages"], 1):
        if not msg.get("timestamp"):
            warnings.append(f"第 {i} 条尚未设置时间。")
            continue
        current = datetime.fromisoformat(msg["timestamp"])
        if previous:
            gap = (current - previous).total_seconds() / 60
            low, high = _interval(rules, msg)
            if gap < 0:
                warnings.append(f"第 {i} 条时间早于上一条。")
            elif gap < low or gap > high:
                warnings.append(f"第 {i} 条与上一条间隔 {gap:g} 分钟，超出当前规则。")
        previous = current
    return warnings
