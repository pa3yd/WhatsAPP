from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from .storage import Store
from .wallpaper import WALLPAPER_DATA_URI


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
        return max(560, min(1000, int(settings.get("width", 560))))
    return max(420, min(1000, int(settings.get("width", 620))))


def _image(store: Store, asset_id: str | None) -> str:
    if not asset_id:
        return ""
    raw = store.image_path(asset_id).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def render_header_preview_html(data: dict, store: Store) -> str:
    """A compact, immediately visible copy of the WhatsApp header while editing."""
    buyer = data["participants"]["buyer"]
    avatar = _image(store, buyer.get("avatar_id"))
    initial = escape((buyer.get("name") or "?")[:1].upper())
    avatar_html = (f'<img class="avatar" src="{avatar}" alt="虚构头像">' if avatar
                   else f'<span class="avatar">{initial}</span>')
    status = _presence_label(buyer, data)
    status_html = f'<small>{escape(status)}</small>' if status else ""
    name = escape(str(buyer.get("name") or "Buyer"))
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
    status = _presence_label(buyer, data) if style in ("classic", "web") else ""
    status_html = f'<small>{escape(status)}</small>' if status else ""
    avatar = _image(store, buyer.get("avatar_id"))
    initials = escape((buyer.get("name") or "?")[:1].upper())
    avatar_html = f'<img class="avatar" src="{avatar}" alt="虚构头像">' if avatar else f'<span class="avatar placeholder">{initials}</span>'
    body = []
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
                long_gap = previous_visible_moment is not None and (moment - previous_visible_moment).total_seconds() >= 30 * 60
                if new_day or long_gap:
                    label = f"{day} {clock}" if new_day else clock
                    body.append(f'<div class="day">{escape(label)}</div>')
            elif day != previous_day:
                body.append(f'<div class="day">{escape(day)}</div>')
            previous_day = day
            previous_visible_moment = moment
        else:
            clock = "--:--"
        side = "out" if msg["sender_id"] == "seller" else "in"
        person = seller if side == "out" else buyer
        name = escape(str(person.get("name") or msg["sender_id"]))
        attachment = ""
        if msg.get("asset_id"):
            src = _image(store, msg["asset_id"])
            attachment = f'<img class="attachment" src="{src}" alt="模拟产品图片">'
        message = escape(str(msg.get("text") or ""))
        sender_avatar = _image(store, person.get("avatar_id")) if style == "wechat" else ""
        sender_initial = escape((person.get("name") or "?")[:1].upper())
        message_avatar = (f'<img class="message-avatar" src="{sender_avatar}" alt="虚构头像">'
                          if sender_avatar else f'<span class="message-avatar placeholder">{sender_initial}</span>') if style == "wechat" else ""
        body.append(f'<div class="row {side}">{message_avatar}<div class="bubble"><div class="sender">{name}</div>{attachment}<div class="text">{message}</div><div class="time">{escape(clock)}</div></div></div>')
    width = render_width(data)
    wechat_css = '''
body.wechat{background:#e2e2e2;color:#191919;font-family:Arial,"Microsoft YaHei",sans-serif}
.wechat .frame{max-width:100%;background:#f5f5f5;box-shadow:0 4px 20px #0002}
.wechat .top{background:#f7f7f7;color:#191919;border-bottom:1px solid #e8e8e8;min-height:58px;padding:10px 15px}
.wechat .top .avatar{display:none}
.wechat .head-main strong{font-size:15px;font-weight:500}
.wechat .toolbar{display:flex;margin-left:auto;align-items:center;gap:20px;color:#555;font-size:20px}
.wechat .chat{min-height:540px;background:#f5f5f5;background-image:none;padding:10px 14px 28px}
.wechat .day{background:transparent;color:#9a9da3;font-size:11px;margin:20px auto 15px;padding:0}
.wechat .row{align-items:flex-start;gap:10px;margin:17px 0}
.wechat .row.out{flex-direction:row-reverse;justify-content:flex-start}
.wechat .message-avatar{width:38px;height:38px;flex:0 0 38px;border-radius:5px;object-fit:cover;background:#c9dcda;display:flex;align-items:center;justify-content:center;font-weight:700;color:#134a46}
.wechat .bubble{min-width:0;max-width:73%;padding:9px 12px;border-radius:5px;box-shadow:none;border:0;background:#e9e9e9;position:relative}
.wechat .out .bubble{background:#95ec8a}
.wechat .bubble:before{content:"";position:absolute;top:13px;left:-5px;width:9px;height:9px;background:#e9e9e9;transform:rotate(45deg)}
.wechat .out .bubble:before{left:auto;right:-5px;background:#95ec8a}
.wechat .sender,.wechat .time,.wechat .text:empty{display:none}
.wechat .text{font-size:14px;line-height:1.5}
.wechat .attachment{border-radius:4px;margin:1px 0 3px}
.wechat .composer{height:52px;background:#f7f7f7;border-top:1px solid #e8e8e8;display:flex;align-items:center;gap:16px;padding:0 15px;color:#555;font-size:22px}
.wechat .composer .entry{height:34px;flex:1;background:#fff;border:1px solid #ededed;border-radius:5px}
'''
    web_css = '''body.web{background:#e9e6df;color:#171e20;font-family:Arial,"Segoe UI","Microsoft YaHei",sans-serif}.web .frame{min-height:650px;box-shadow:0 2px 16px #0002;background:#f4f0e9}.web .top{height:60px;background:#fafaf9;color:#182229;border-bottom:1px solid #e7e5e1;padding:8px 16px;gap:11px}.web .avatar{width:39px;height:39px;background:#d6e5dd;color:#405e55;font-size:15px}.web .head-main strong{font-size:14px;font-weight:600}.web .head-main small{display:block;color:#64716e;opacity:1;font-size:11px;margin-top:2px}.web .toolbar{display:flex;margin-left:auto;gap:22px;color:#58655f;font-size:19px;align-items:center}.web .notice{background:#fff7d6;color:#694d16;padding:6px 12px;font-size:10px;letter-spacing:.3px;border-bottom:1px solid #e8d49e}.web .chat{min-height:510px;padding:12px 44px 35px;background-color:#f3efe8;background-image:radial-gradient(circle at 17px 16px,#d8cfbe40 1px,transparent 1.6px),radial-gradient(circle at 55px 48px,#d8cfbe35 1.2px,transparent 1.8px);background-size:76px 67px}.web .day{background:#fffaf2d9;color:#72746f;font-size:11px;padding:5px 9px;border-radius:6px;box-shadow:0 1px 1px #0001}.web .row{margin:5px 0}.web .bubble{max-width:67%;min-width:85px;padding:6px 8px 4px;border-radius:7px;box-shadow:0 1px 1px #0002;background:#fff}.web .out .bubble{background:#d9f5d1}.web .sender{display:none}.web .text{font-size:13px;line-height:1.43}.web .time{font-size:10px;color:#82908a;margin-top:2px}.web .composer{height:52px;background:#f8f8f7;border-top:1px solid #e1e1df;display:flex;align-items:center;gap:14px;padding:0 17px;color:#65716c}.web .composer .entry{background:#fff;border-radius:8px;height:34px;flex:1;padding:9px 12px;color:#909a95;font-size:12px}.web .foot{background:#fff7d6;color:#694d16;font-size:10px;padding:7px}.web.neutral .frame{background:#eef1f1}.web.neutral .chat{background-color:#e9eeee;background-image:radial-gradient(circle at 17px 16px,#c4d2d140 1px,transparent 1.6px),radial-gradient(circle at 55px 48px,#c4d2d135 1.2px,transparent 1.8px);background-size:76px 67px}.web.neutral .out .bubble{background:#dcf2e7}.web.neutral .notice,.web.neutral .foot{background:#eef4ed;color:#4e695f;border-color:#c9dbd1}'''
    classic_css = '''.classic .top{min-height:64px}.classic .toolbar{display:flex;margin-left:auto;align-items:center;gap:17px;font-size:20px;font-weight:400}.classic .composer{display:flex;align-items:center;gap:11px;padding:8px 12px;background:#eeeae2;color:#687472;font-size:22px}.classic .composer .entry{flex:1;min-width:0;background:white;border-radius:22px;padding:10px 15px;color:#89928f;font-size:13px}.classic .composer .mic{width:37px;height:37px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#1c6662;color:#fff;font-size:17px}'''
    realism_css = f'''
body.web,body.classic{{font-family:"Segoe UI","Helvetica Neue",Arial,"Microsoft YaHei",sans-serif}}
.web .chat,.web.neutral .chat,.classic .chat{{background-color:#f8f4ee;background-image:url("{WALLPAPER_DATA_URI}");background-size:560px 560px}}
.web .top,.classic .top{{background:#f8f9fa;color:#17252a;border-bottom:1px solid #e5e8e7}}
.web .head-main strong,.classic .head-main strong{{font-weight:500;line-height:1.2}}
.web .head-main small,.classic .head-main small{{display:block;color:#68777b;opacity:1;font-size:11px;font-weight:400;margin-top:3px;white-space:nowrap}}
.web .toolbar,.classic .toolbar{{color:#54656f}}
.web .text{{font-size:14px;line-height:1.45}}
.web .out .bubble,.classic .out .bubble{{background:#d9fdd3}}
.web .bubble{{padding:7px 9px 5px}}
.classic .top{{min-height:61px;padding:9px 14px}}
.classic .chat{{min-height:510px}}
'''
    video_icon = '<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="2" y="6" width="14" height="12" rx="2"/><path d="m16 10 6-4v12l-6-4"/></svg>'
    phone_icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h4l1 5-2 2a15 15 0 0 0 5 5l2-2 5 1v4a3 3 0 0 1-3 3C10 21 3 14 3 6a3 3 0 0 1 3-3Z"/></svg>'
    mic_icon = '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4m-4 0h8"/></svg>'
    search_icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>'
    toolbar = (f'<div class="toolbar" aria-hidden="true">{video_icon}{phone_icon}{search_icon}<span>⋮</span></div>' if style == "web"
               else '<div class="toolbar" aria-hidden="true"><span>☏</span><span>⋯</span></div>' if style == "wechat"
               else f'<div class="toolbar" aria-hidden="true">{video_icon}{phone_icon}<span>⋮</span></div>')
    composer = ('<div class="composer" aria-hidden="true"><span>＋</span><span>☺</span><div class="entry">输入消息</div><span>◉</span></div>' if style == "web"
                else '<div class="composer" aria-hidden="true"><span>☰</span><div class="entry"></div><span>☺</span><span>＋</span></div>' if style == "wechat"
                else f'<div class="composer" aria-hidden="true"><span>☺</span><div class="entry">Message</div><span>＋</span><span class="mic">{mic_icon}</span></div>')
    return f'''<!doctype html><html lang="{escape(str(data.get("language", "en")))}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:#e9e7e1;color:#18272b;font-family:Arial,"Noto Sans",sans-serif}}.frame{{width:{width}px;margin:auto;background:#efeae2;min-height:420px;box-shadow:0 4px 20px #0002}}.top{{background:#1c6662;color:white;padding:13px 18px;display:flex;align-items:center;gap:12px}}.avatar{{height:42px;width:42px;border-radius:50%;object-fit:cover;display:inline-flex;align-items:center;justify-content:center;background:#c9dcda;color:#134a46;font-weight:700}}.head-main{{min-width:0}}.head-main strong{{display:block;font-size:16px}}.head-main small{{opacity:.84}}.notice{{background:#fff4cf;color:#5d4210;text-align:center;padding:9px 12px;font-weight:800;font-size:12px;letter-spacing:.4px;border-bottom:2px solid #dba530}}.chat{{padding:12px 17px 25px;background-color:#e8e3d9;background-image:radial-gradient(#ffffff55 1px,transparent 1px);background-size:22px 22px}}.day{{width:max-content;margin:11px auto;padding:5px 10px;border-radius:7px;background:#e0f0ed;font-size:11px;color:#44615f}}.row{{display:flex;margin:8px 0}}.out{{justify-content:flex-end}}.bubble{{max-width:79%;min-width:110px;padding:8px 10px 5px;border-radius:9px;background:white;box-shadow:0 1px 2px #0002;overflow-wrap:anywhere}}.out .bubble{{background:#d6f2cf}}.sender{{font-size:12px;font-weight:bold;color:#327271;margin-bottom:3px}}.classic .sender{{display:none}}.text{{white-space:pre-wrap;font-size:14px;line-height:1.45}}.attachment{{display:block;max-width:100%;max-height:430px;object-fit:contain;border-radius:6px;margin:4px 0 7px}}.time{{text-align:right;font-size:10px;color:#687779;margin-top:3px}}.foot{{padding:10px;text-align:center;background:#fff4cf;font-size:11px;font-weight:800;color:#5d4210}}
{wechat_css}
{web_css}
{classic_css}
{realism_css}
</style></head><body class="{style} {tone}"><div class="frame"><header class="top">{avatar_html}<div class="head-main"><strong>{escape(str(buyer.get("name") or "Buyer"))}</strong>{status_html}</div>{toolbar}</header><main class="chat">{''.join(body)}</main>{composer}</div></body></html>'''
