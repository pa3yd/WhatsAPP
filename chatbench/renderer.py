from __future__ import annotations

import base64
import re
from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from .storage import Store
from .models import sender_options
from .wallpaper import WALLPAPER_DATA_URI


def _wechat_time_label(moment: datetime, conversation_day: str) -> str:
    reference = date.fromisoformat(conversation_day)
    if moment.date() == reference:
        return moment.strftime("%H:%M")
    if moment.date() == reference - timedelta(days=1):
        return f"昨天 {moment:%H:%M}"
    if moment.year == reference.year:
        return f"{moment.month}月{moment.day}日 {moment:%H:%M}"
    return f"{moment.year}年{moment.month}月{moment.day}日 {moment:%H:%M}"


def _presence_label(buyer: dict, data: dict) -> str:
    mode = buyer.get("presence_mode", "hidden")
    if mode == "online":
        return "在线"
    if mode != "last_seen" or not buyer.get("last_seen_at"):
        return ""
    moment = datetime.fromisoformat(buyer["last_seen_at"]).astimezone(ZoneInfo(data["timezone"]))
    chat_day = date.fromisoformat(data["conversation_date"])
    if moment.date() == chat_day:
        when = f"今天 {moment:%H:%M}"
    elif moment.date() == chat_day - timedelta(days=1):
        when = f"昨天 {moment:%H:%M}"
    else:
        when = moment.strftime("%Y-%m-%d %H:%M")
    return f"最后上线时间：{when}"

def render_width(data: dict) -> int:
    settings = data.get("render_settings", {})
    if settings.get("style") == "web":
        return 1000
    if settings.get("style") == "wechat":
        return max(720, min(1000, int(settings.get("width", 720))))
    return max(420, min(1000, int(settings.get("width", 620))))


def _image(store: Store, asset_id: str | None) -> str:
    if not asset_id:
        return ""
    raw = store.image_path(asset_id).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def render_header_preview_html(data: dict, store: Store) -> str:
    """A compact, immediately visible copy of the WhatsApp header while editing."""
    buyer = data["participants"]["buyer"]
    group = data.get("group", {})
    is_group = bool(group.get("enabled"))
    avatar = _image(store, buyer.get("avatar_id")) if not is_group else ""
    title = group.get("name") if is_group else buyer.get("name")
    initial = escape((title or "?")[:1].upper())
    avatar_html = (f'<img class="avatar" src="{avatar}" alt="虚构头像">' if avatar
                   else f'<span class="avatar">{initial}</span>')
    status = ", ".join(person.get("name", "") for person in sender_options(data).values()) if is_group else _presence_label(buyer, data)
    status_html = f'<small>{escape(status)}</small>' if status else ""
    name = escape(str(title or "Group"))
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}html,body{{margin:0;background:#f8f9fa;font-family:"Segoe UI","Helvetica Neue",Arial,"Microsoft YaHei",sans-serif;color:#17252a}}
.top{{height:64px;padding:9px 14px;display:flex;align-items:center;gap:12px;border:1px solid #e5e8e7}}
.avatar{{width:42px;height:42px;border-radius:50%;object-fit:cover;display:inline-flex;align-items:center;justify-content:center;background:#d6e5dd;color:#405e55;font-size:15px;font-weight:700;flex:0 0 42px}}
strong{{display:block;font-size:15px;font-weight:500;line-height:1.2}}small{{display:block;font-size:11px;color:#68777b;margin-top:3px}}
</style></head><body><header class="top">{avatar_html}<div><strong>{name}</strong>{status_html}</div></header></body></html>'''


def render_html(data: dict, store: Store) -> str:
    style = data.get("render_settings", {}).get("style", "classic")
    tone = data.get("render_settings", {}).get("tone", "warm")
    if style not in ("classic", "wechat", "web"):
        raise ValueError("不支持的聊天界面样式。")
    if tone not in ("warm", "neutral"):
        raise ValueError("不支持的聊天色调。")
    buyer = data["participants"]["buyer"]
    seller = data["participants"]["seller"]
    group = data.get("group", {})
    is_group = bool(group.get("enabled"))
    people = sender_options(data)
    status = _presence_label(buyer, data) if style in ("classic", "web") else ""
    status_html = f'<small>{escape(status)}</small>' if status else ""
    avatar = _image(store, buyer.get("avatar_id"))
    initials = escape((buyer.get("name") or "?")[:1].upper())
    avatar_html = f'<img class="avatar" src="{avatar}" alt="虚构头像">' if avatar else f'<span class="avatar placeholder">{initials}</span>'
    body = []
    time_gap_minutes = data.get("render_settings", {}).get("wechat_time_gap_minutes", 5)
    previous_day = None
    previous_visible_moment = None
    for msg in data["messages"]:
        if style == "wechat" and not str(msg.get("text") or "").strip() and not msg.get("asset_id"):
            continue
        raw_time = msg.get("timestamp")
        if raw_time:
            moment = datetime.fromisoformat(raw_time).astimezone(ZoneInfo(data["timezone"]))
            day = moment.strftime("%Y-%m-%d")
            clock = moment.strftime("%H:%M")
            if style == "wechat":
                new_day = day != previous_day
                long_gap = (previous_visible_moment is not None
                            and moment.timestamp() - previous_visible_moment.timestamp() >= time_gap_minutes * 60)
                if previous_visible_moment is None or new_day or long_gap or msg.get("show_time_label", False):
                    label = _wechat_time_label(moment, data["conversation_date"])
                    body.append(f'<div class="day">{escape(label)}</div>')
            elif day != previous_day:
                body.append(f'<div class="day">{escape(day)}</div>')
            previous_day = day
            previous_visible_moment = moment
        else:
            clock = "--:--"
            previous_visible_moment = None
        side = "out" if msg["sender_id"] == "seller" else "in"
        person = people[msg["sender_id"]]
        name = escape(str(person.get("name") or msg["sender_id"]))
        attachment = ""
        if msg.get("asset_id"):
            src = _image(store, msg["asset_id"])
            attachment = f'<img class="attachment" src="{src}" alt="模拟产品图片">'
        message = escape(str(msg.get("text") or "").strip() if style == "wechat" else str(msg.get("text") or ""))
        sender_avatar = _image(store, person.get("avatar_id")) if style == "wechat" or (is_group and style == "classic" and side == "in") else ""
        sender_initial = escape((person.get("name") or "?")[:1].upper())
        message_avatar = (f'<img class="message-avatar" src="{sender_avatar}" alt="虚构头像">'
                          if sender_avatar else f'<span class="message-avatar placeholder">{sender_initial}</span>') if style == "wechat" or (is_group and style == "classic" and side == "in") else ""
        read_mark = '<span class="read-mark" aria-hidden="true">✓✓</span>' if style == "classic" and side == "out" else ""
        content = f'{attachment}<div class="text">{message}</div><div class="time">{escape(clock)}{read_mark}</div>'
        if style == "wechat" and is_group:
            nickname = f'<div class="sender">{name}</div>' if side == "in" else ""
            body.append(f'<div class="row {side}">{message_avatar}<div class="message-content">{nickname}<div class="bubble">{content}</div></div></div>')
        else:
            body.append(f'<div class="row {side}">{message_avatar}<div class="bubble"><div class="sender">{name}</div>{content}</div></div>')
    width = render_width(data)
    wechat_css = '''
body.wechat{background:#e0e0e0;color:#19191a;font-family:"Microsoft YaHei UI","Microsoft YaHei","PingFang SC",sans-serif}
.wechat .frame{max-width:100%;background:#fafafa;box-shadow:0 4px 20px #0002}
.wechat .top{background:#f7f7f7;color:#191919;border-bottom:1px solid #e8e8e8;min-height:58px;padding:10px 15px}
.wechat .top .avatar{display:none}
.wechat .head-main strong{font-size:15px;font-weight:500}
.wechat .toolbar{display:flex;margin-left:auto;align-items:center;gap:20px;color:#555;font-size:20px}
.wechat .chat{min-height:540px;background:#fafafa;background-image:none;padding:10px 20px 28px}
.wechat .day{background:transparent;color:#96989f;font-size:12px;line-height:18px;margin:26px auto 22px;padding:0}
.wechat .row{align-items:flex-start;gap:10px;margin:17px 0}
.wechat .row.out{flex-direction:row-reverse;justify-content:flex-start}
.wechat .message-avatar{width:38px;height:38px;flex:0 0 38px;border-radius:5px;object-fit:cover;background:#c9dcda;display:flex;align-items:center;justify-content:center;font-weight:700;color:#134a46}
.wechat .bubble{min-width:0;max-width:70%;flex:0 1 auto;padding:8px 11px;border-radius:5px;box-shadow:none;border:0;background:#eeeef0;position:relative}
.wechat .out .bubble{background:#9df29f}
.wechat .bubble:before{content:"";position:absolute;top:13px;left:-5px;width:9px;height:9px;background:#eeeef0;transform:rotate(45deg)}
.wechat .out .bubble:before{left:auto;right:-5px;background:#9df29f}
.wechat .sender,.wechat .time,.wechat .text:empty{display:none}
.wechat .text{font-size:14px;line-height:1.45;text-wrap:wrap}
.wechat .attachment{border-radius:4px;margin:1px 0 3px}
.wechat .composer{height:52px;background:#f7f7f7;border-top:1px solid #e8e8e8;display:flex;align-items:center;gap:16px;padding:0 15px;color:#555;font-size:22px}
.wechat .composer .entry{height:34px;flex:1;background:#fff;border:1px solid #ededed;border-radius:5px}
.wechat.group .row{margin:18px 0 20px}
.wechat.group .message-content{min-width:0;max-width:70%;flex:0 1 auto;display:flex;flex-direction:column;align-items:flex-start}
.wechat.group .out .message-content{align-items:flex-end}
.wechat.group .bubble{max-width:100%}
.wechat.group .row.in .sender{display:block;max-width:100%;overflow-wrap:anywhere;color:#96989f;font-size:12px;line-height:16px;font-weight:400;margin:0 0 4px}
.wechat.group .row.out .sender{display:none}
'''
    web_css = '''body.web{background:#e9e6df;color:#171e20;font-family:Arial,"Segoe UI","Microsoft YaHei",sans-serif}.web .frame{min-height:650px;box-shadow:0 2px 16px #0002;background:#f4f0e9}.web .top{height:60px;background:#fafaf9;color:#182229;border-bottom:1px solid #e7e5e1;padding:8px 16px;gap:11px}.web .avatar{width:39px;height:39px;background:#d6e5dd;color:#405e55;font-size:15px}.web .head-main strong{font-size:14px;font-weight:600}.web .head-main small{display:block;color:#64716e;opacity:1;font-size:11px;margin-top:2px}.web .toolbar{display:flex;margin-left:auto;gap:22px;color:#58655f;font-size:19px;align-items:center}.web .notice{background:#fff7d6;color:#694d16;padding:6px 12px;font-size:10px;letter-spacing:.3px;border-bottom:1px solid #e8d49e}.web .chat{min-height:510px;padding:12px 44px 35px;background-color:#f3efe8;background-image:radial-gradient(circle at 17px 16px,#d8cfbe40 1px,transparent 1.6px),radial-gradient(circle at 55px 48px,#d8cfbe35 1.2px,transparent 1.8px);background-size:76px 67px}.web .day{background:#fffaf2d9;color:#72746f;font-size:11px;padding:5px 9px;border-radius:6px;box-shadow:0 1px 1px #0001}.web .row{margin:5px 0}.web .bubble{max-width:67%;min-width:85px;padding:6px 8px 4px;border-radius:7px;box-shadow:0 1px 1px #0002;background:#fff}.web .out .bubble{background:#d9f5d1}.web .sender{display:none}.web .text{font-size:13px;line-height:1.43}.web .time{font-size:10px;color:#82908a;margin-top:2px}.web .composer{height:52px;background:#f8f8f7;border-top:1px solid #e1e1df;display:flex;align-items:center;gap:14px;padding:0 17px;color:#65716c}.web .composer .entry{background:#fff;border-radius:8px;height:34px;flex:1;padding:9px 12px;color:#909a95;font-size:12px}.web .foot{background:#fff7d6;color:#694d16;font-size:10px;padding:7px}.web.neutral .frame{background:#eef1f1}.web.neutral .chat{background-color:#e9eeee;background-image:radial-gradient(circle at 17px 16px,#c4d2d140 1px,transparent 1.6px),radial-gradient(circle at 55px 48px,#c4d2d135 1.2px,transparent 1.8px);background-size:76px 67px}.web.neutral .out .bubble{background:#dcf2e7}.web.neutral .notice,.web.neutral .foot{background:#eef4ed;color:#4e695f;border-color:#c9dbd1}'''
    classic_css = '''
body.classic{background:#e7e5e0;color:#151515;font-family:"Segoe UI Emoji","Microsoft YaHei UI","Microsoft YaHei",Arial,sans-serif}
.classic .frame{background:#f8f7f4;box-shadow:0 4px 20px #0002}
.classic .status-bar{height:32px;padding:5px 19px 0;display:flex;align-items:center;justify-content:space-between;background:#fafaf9;color:#111;font-size:14px;font-weight:700}
.classic .status-icons{display:flex;align-items:center;gap:6px}
.classic .status-icons svg{display:block}
.classic .top{min-height:62px;padding:7px 12px;background:#fafaf9;color:#151515;border-bottom:1px solid #e7e7e5;gap:9px}
.classic .back{display:block;color:#151515;font-size:29px;line-height:1;margin-right:2px;font-weight:300}
.classic .avatar{width:39px;height:39px;flex:0 0 39px;background:#d9dce0;color:#5b626a}
.classic .head-main strong{font-size:15px;font-weight:600;line-height:1.25}
.classic .head-main small{display:block;color:#8a8a8a;opacity:1;font-size:11px;margin-top:2px}
.classic .toolbar{display:flex;margin-left:auto;align-items:center;gap:16px;color:#1d2425;font-size:22px}
.classic .chat{min-height:510px;padding:14px 12px 30px;background-color:#f8f4ee}
.classic .day{background:#fffefa;color:#3e4242;border-radius:10px;box-shadow:0 1px 2px #0002;font-size:11px;font-weight:600;padding:4px 9px;margin:12px auto}
.classic .row{margin:8px 0}
.classic .bubble{min-width:0;max-width:82%;padding:7px 9px 5px;border-radius:9px;background:#fff;box-shadow:0 1px 2px #0002;position:relative}
.classic .out .bubble{background:#d5fbd1}
.classic .bubble:before{content:"";position:absolute;top:11px;left:-4px;width:9px;height:9px;transform:rotate(45deg);background:#fff}
.classic .out .bubble:before{left:auto;right:-4px;background:#d5fbd1}
.classic .sender{display:none}
.classic .text{font-size:14px;line-height:1.45;overflow-wrap:anywhere}
.classic .time{font-size:10px;color:#78827c;margin-top:2px}
.classic .read-mark{color:#1685c5;font-size:13px;letter-spacing:-5px;font-weight:700;margin:0 5px 0 4px}
.classic .composer{height:58px;display:flex;align-items:center;gap:10px;padding:7px 12px;background:#fafaf9;border-top:1px solid #e4e4e1;color:#1b2225;font-size:24px}
.classic .composer .entry{flex:1;min-width:0;height:36px;background:#fff;border:1px solid #dededb;border-radius:20px;padding:8px 13px;color:#89928f;font-size:13px}
.classic .composer .mic{display:flex;align-items:center;justify-content:center;background:none;color:#1b2225;width:auto;height:auto;font-size:22px}
.classic .home-indicator{height:22px;background:#fafaf9;display:flex;align-items:flex-end;justify-content:center;padding-bottom:5px}
.classic .home-indicator:after{content:"";display:block;width:108px;height:4px;border-radius:4px;background:#111}
.classic.group .row.in{align-items:flex-end;gap:6px}
.classic.group .message-avatar{width:27px;height:27px;flex:0 0 27px;border-radius:50%;object-fit:cover;background:#d9dce0;color:#5b626a;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
.classic.group .row.in .sender{display:block;color:#42857d;font-size:11px;font-weight:600;margin-bottom:3px}
.classic.group .row.out .sender{display:none}
'''
    realism_css = f'''
body.web{{font-family:"Segoe UI","Helvetica Neue",Arial,"Microsoft YaHei",sans-serif}}
.web .chat,.web.neutral .chat,.classic .chat{{background-color:#f8f4ee;background-image:url("{WALLPAPER_DATA_URI}");background-size:560px 560px}}
.web .top{{background:#f8f9fa;color:#17252a;border-bottom:1px solid #e5e8e7}}
.web .head-main strong{{font-weight:500;line-height:1.2}}
.web .head-main small{{display:block;color:#68777b;opacity:1;font-size:11px;font-weight:400;margin-top:3px;white-space:nowrap}}
.web .toolbar{{color:#54656f}}
.web .text{{font-size:14px;line-height:1.45}}
.web .out .bubble{{background:#d9fdd3}}
.web .bubble{{padding:7px 9px 5px}}
.classic .chat{{background-image:url("{WALLPAPER_DATA_URI}")}}
'''
    video_icon = '<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="2" y="6" width="14" height="12" rx="2"/><path d="m16 10 6-4v12l-6-4"/></svg>'
    phone_icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h4l1 5-2 2a15 15 0 0 0 5 5l2-2 5 1v4a3 3 0 0 1-3 3C10 21 3 14 3 6a3 3 0 0 1 3-3Z"/></svg>'
    mic_icon = '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4m-4 0h8"/></svg>'
    search_icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>'
    conversation_icon = '<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10.5a9 7.5 0 0 1-9 7.5H8l-5 3 1-6A7 7 0 0 1 3 10.5a9 7.5 0 0 1 18 0Z"/><path d="M8 11h.1m3.9 0h.1m3.9 0h.1"/></svg>'
    toolbar = (f'<div class="toolbar" aria-hidden="true">{video_icon}{phone_icon}{search_icon}<span>⋮</span></div>' if style == "web"
               else f'<div class="toolbar" aria-hidden="true">{conversation_icon}{phone_icon}<span>⋯</span></div>' if style == "wechat"
               else f'<div class="toolbar" aria-hidden="true">{video_icon}{phone_icon}<span>⋮</span></div>')
    composer = ('<div class="composer" aria-hidden="true"><span>＋</span><span>☺</span><div class="entry">输入消息</div><span>◉</span></div>' if style == "web"
                else '<div class="composer" aria-hidden="true"><span>☰</span><div class="entry"></div><span>☺</span><span>＋</span></div>' if style == "wechat"
                else f'<div class="composer" aria-hidden="true"><span>＋</span><div class="entry"></div><span>☺</span><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 7h4l2-2h4l2 2h4v12H4z"/><circle cx="12" cy="13" r="3.5"/></svg><span class="mic">{mic_icon}</span></div>')
    last_timestamp = next((m.get("timestamp") for m in reversed(data["messages"]) if m.get("timestamp")), None)
    device_clock = datetime.fromisoformat(last_timestamp).astimezone(ZoneInfo(data["timezone"])).strftime("%H:%M") if last_timestamp else "09:41"
    status_icons = '<svg width="18" height="14" viewBox="0 0 18 14" fill="currentColor"><rect x="1" y="9" width="3" height="4" rx="1"/><rect x="6" y="6" width="3" height="7" rx="1"/><rect x="11" y="3" width="3" height="10" rx="1"/></svg><svg width="18" height="14" viewBox="0 0 18 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M1 5c4-4 12-4 16 0M4 8c3-3 7-3 10 0M8 11c1-1 2-1 3 0"/></svg><svg width="23" height="13" viewBox="0 0 23 13" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1" y="1" width="18" height="11" rx="2"/><rect x="3" y="3" width="13" height="7" rx="1" fill="currentColor" stroke="none"/><path d="M21 5v3"/></svg>'
    status_bar = f'<div class="status-bar"><span>{escape(device_clock)}</span><span class="status-icons">{status_icons}</span></div>' if style == "classic" else ""
    back_arrow = '<span class="back" aria-hidden="true">‹</span>' if style == "classic" else ""
    home_indicator = '<div class="home-indicator" aria-hidden="true"></div>' if style == "classic" else ""
    header_name = group.get("name") if is_group else buyer.get("name")
    if style == "wechat" and is_group:
        group_title = re.sub(r"\s*[（(]\d+[)）]\s*$", "", str(header_name or "群聊"))
        header_name = f"{group_title} ({len(people)})"
    header_avatar = (f'<span class="avatar placeholder">♟</span>' if is_group else avatar_html)
    group_names = ", ".join(person.get("name", "") for person in people.values()) if is_group else ""
    header_status = (f'<small>{escape(group_names)}</small>' if style != "wechat" else "") if is_group else status_html
    return f'''<!doctype html><html lang="{escape(str(data.get("language", "en")))}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:#e9e7e1;color:#18272b;font-family:Arial,"Noto Sans",sans-serif}}.frame{{width:{width}px;margin:auto;background:#efeae2;min-height:420px;box-shadow:0 4px 20px #0002}}.top{{background:#1c6662;color:white;padding:13px 18px;display:flex;align-items:center;gap:12px}}.avatar{{height:42px;width:42px;border-radius:50%;object-fit:cover;display:inline-flex;align-items:center;justify-content:center;background:#c9dcda;color:#134a46;font-weight:700}}.head-main{{min-width:0}}.head-main strong{{display:block;font-size:16px}}.head-main small{{opacity:.84}}.notice{{background:#fff4cf;color:#5d4210;text-align:center;padding:9px 12px;font-weight:800;font-size:12px;letter-spacing:.4px;border-bottom:2px solid #dba530}}.chat{{padding:12px 17px 25px;background-color:#e8e3d9;background-image:radial-gradient(#ffffff55 1px,transparent 1px);background-size:22px 22px}}.day{{width:max-content;margin:11px auto;padding:5px 10px;border-radius:7px;background:#e0f0ed;font-size:11px;color:#44615f}}.row{{display:flex;margin:8px 0}}.out{{justify-content:flex-end}}.bubble{{max-width:79%;min-width:110px;padding:8px 10px 5px;border-radius:9px;background:white;box-shadow:0 1px 2px #0002;overflow-wrap:anywhere}}.out .bubble{{background:#d6f2cf}}.sender{{font-size:12px;font-weight:bold;color:#327271;margin-bottom:3px}}.classic .sender{{display:none}}.text{{white-space:pre-wrap;font-size:14px;line-height:1.45}}.attachment{{display:block;max-width:100%;max-height:430px;object-fit:contain;border-radius:6px;margin:4px 0 7px}}.time{{text-align:right;font-size:10px;color:#687779;margin-top:3px}}.foot{{padding:10px;text-align:center;background:#fff4cf;font-size:11px;font-weight:800;color:#5d4210}}
{wechat_css}
{web_css}
{classic_css}
{realism_css}
</style></head><body class="{style} {tone}{' group' if is_group else ''}"><div class="frame">{status_bar}<header class="top">{back_arrow}{header_avatar}<div class="head-main"><strong>{escape(str(header_name or 'Group'))}</strong>{header_status}</div>{toolbar}</header><main class="chat">{''.join(body)}</main>{composer}{home_indicator}</div></body></html>'''
