from __future__ import annotations

import base64
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .storage import Store

def render_width(data: dict) -> int:
    settings = data.get("render_settings", {})
    if settings.get("style") == "web":
        return 1000
    return max(420, min(1000, int(settings.get("width", 620))))


def _image(store: Store, asset_id: str | None) -> str:
    if not asset_id:
        return ""
    raw = store.image_path(asset_id).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def render_html(data: dict, store: Store) -> str:
    style = data.get("render_settings", {}).get("style", "classic")
    tone = data.get("render_settings", {}).get("tone", "warm")
    if style not in ("classic", "wechat", "web"):
        raise ValueError("不支持的聊天界面样式。")
    if tone not in ("warm", "neutral"):
        raise ValueError("不支持的聊天色调。")
    buyer = data["participants"]["buyer"]
    seller = data["participants"]["seller"]
    avatar = _image(store, buyer.get("avatar_id"))
    initials = escape((buyer.get("name") or "?")[:1].upper())
    avatar_html = f'<img class="avatar" src="{avatar}" alt="虚构头像">' if avatar else f'<span class="avatar placeholder">{initials}</span>'
    body = []
    previous_day = None
    for msg in data["messages"]:
        raw_time = msg.get("timestamp")
        if raw_time:
            moment = datetime.fromisoformat(raw_time).astimezone(ZoneInfo(data["timezone"]))
            day = moment.strftime("%Y-%m-%d")
            clock = moment.strftime("%H:%M")
            if day != previous_day:
                body.append(f'<div class="day">{escape(day)}</div>')
                previous_day = day
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
    wechat_css = '''body.wechat{background:#d7d7d7;color:#191919;font-family:Arial,"Microsoft YaHei",sans-serif}.wechat .frame{background:#ededed;box-shadow:0 4px 20px #0002}.wechat .top{background:#f5f5f5;color:#191919;border-bottom:1px solid #d8d8d8;justify-content:center;min-height:62px}.wechat .top .avatar,.wechat .top small{display:none}.wechat .head-main strong{font-weight:600}.wechat .chat{background:#ededed;background-image:none;padding:10px 13px 25px}.wechat .day{background:#d5d5d5;color:#fff;border-radius:4px}.wechat .row{align-items:flex-start;gap:9px;margin:13px 0}.wechat .row.out{flex-direction:row-reverse}.wechat .message-avatar{width:38px;height:38px;flex:0 0 38px;border-radius:4px;object-fit:cover;background:#c9dcda;display:flex;align-items:center;justify-content:center;font-weight:700;color:#134a46}.wechat .bubble{min-width:0;max-width:75%;padding:8px 10px 5px;border-radius:5px;box-shadow:none;border:1px solid #dedede;background:#fff;position:relative}.wechat .out .bubble{background:#95ec69;border-color:#8bdf62}.wechat .bubble:before{content:"";position:absolute;top:12px;left:-6px;width:9px;height:9px;background:#fff;border-left:1px solid #dedede;border-bottom:1px solid #dedede;transform:rotate(45deg)}.wechat .out .bubble:before{left:auto;right:-6px;background:#95ec69;border:0;border-top:1px solid #8bdf62;border-right:1px solid #8bdf62}.wechat .sender{display:none}.wechat .text{font-size:15px}.wechat .time{color:#65716a}.wechat .notice,.wechat .foot{background:#fff4cf}'''
    web_css = '''body.web{background:#e9e6df;color:#171e20;font-family:Arial,"Segoe UI","Microsoft YaHei",sans-serif}.web .frame{min-height:650px;box-shadow:0 2px 16px #0002;background:#f4f0e9}.web .top{height:60px;background:#fafaf9;color:#182229;border-bottom:1px solid #e7e5e1;padding:8px 16px;gap:11px}.web .avatar{width:39px;height:39px;background:#d6e5dd;color:#405e55;font-size:15px}.web .head-main strong{font-size:14px;font-weight:600}.web .head-main small{display:block;color:#64716e;opacity:1;font-size:11px;margin-top:2px}.web .toolbar{display:flex;margin-left:auto;gap:22px;color:#58655f;font-size:19px;align-items:center}.web .notice{background:#fff7d6;color:#694d16;padding:6px 12px;font-size:10px;letter-spacing:.3px;border-bottom:1px solid #e8d49e}.web .sub{font-size:11px;color:#7d817d;padding:7px}.web .chat{min-height:510px;padding:12px 44px 35px;background-color:#f3efe8;background-image:radial-gradient(circle at 17px 16px,#d8cfbe40 1px,transparent 1.6px),radial-gradient(circle at 55px 48px,#d8cfbe35 1.2px,transparent 1.8px);background-size:76px 67px}.web .day{background:#fffaf2d9;color:#72746f;font-size:11px;padding:5px 9px;border-radius:6px;box-shadow:0 1px 1px #0001}.web .row{margin:5px 0}.web .bubble{max-width:67%;min-width:85px;padding:6px 8px 4px;border-radius:7px;box-shadow:0 1px 1px #0002;background:#fff}.web .out .bubble{background:#d9f5d1}.web .sender{display:none}.web .text{font-size:13px;line-height:1.43}.web .time{font-size:10px;color:#82908a;margin-top:2px}.web .composer{height:52px;background:#f8f8f7;border-top:1px solid #e1e1df;display:flex;align-items:center;gap:14px;padding:0 17px;color:#65716c}.web .composer .entry{background:#fff;border-radius:8px;height:34px;flex:1;padding:9px 12px;color:#909a95;font-size:12px}.web .foot{background:#fff7d6;color:#694d16;font-size:10px;padding:7px}.web.neutral .frame{background:#eef1f1}.web.neutral .chat{background-color:#e9eeee;background-image:radial-gradient(circle at 17px 16px,#c4d2d140 1px,transparent 1.6px),radial-gradient(circle at 55px 48px,#c4d2d135 1.2px,transparent 1.8px)}.web.neutral .out .bubble{background:#dcf2e7}.web.neutral .notice,.web.neutral .foot{background:#eef4ed;color:#4e695f;border-color:#c9dbd1}'''
    toolbar = '<div class="toolbar" aria-hidden="true"><span>⌕</span><span>⋮</span></div>' if style == "web" else ""
    composer = '<div class="composer" aria-hidden="true"><span>＋</span><span>☺</span><div class="entry">输入消息</div><span>◉</span></div>' if style == "web" else ""
    return f'''<!doctype html><html lang="{escape(str(data.get("language", "en")))}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:#e9e7e1;color:#18272b;font-family:Arial,"Noto Sans",sans-serif}}.frame{{width:{width}px;margin:auto;background:#efeae2;min-height:420px;box-shadow:0 4px 20px #0002}}.top{{background:#1c6662;color:white;padding:13px 18px;display:flex;align-items:center;gap:12px}}.avatar{{height:42px;width:42px;border-radius:50%;object-fit:cover;display:inline-flex;align-items:center;justify-content:center;background:#c9dcda;color:#134a46;font-weight:700}}.head-main{{min-width:0}}.head-main strong{{display:block;font-size:16px}}.head-main small{{opacity:.84}}.notice{{background:#fff4cf;color:#5d4210;text-align:center;padding:9px 12px;font-weight:800;font-size:12px;letter-spacing:.4px;border-bottom:2px solid #dba530}}.sub{{text-align:center;font-size:12px;padding:8px;color:#59666a}}.chat{{padding:12px 17px 25px;background-color:#e8e3d9;background-image:radial-gradient(#ffffff55 1px,transparent 1px);background-size:22px 22px}}.day{{width:max-content;margin:11px auto;padding:5px 10px;border-radius:7px;background:#e0f0ed;font-size:11px;color:#44615f}}.row{{display:flex;margin:8px 0}}.out{{justify-content:flex-end}}.bubble{{max-width:79%;min-width:110px;padding:8px 10px 5px;border-radius:9px;background:white;box-shadow:0 1px 2px #0002;overflow-wrap:anywhere}}.out .bubble{{background:#d6f2cf}}.sender{{font-size:12px;font-weight:bold;color:#327271;margin-bottom:3px}}.out .sender{{color:#4b7050}}.text{{white-space:pre-wrap;font-size:14px;line-height:1.45}}.attachment{{display:block;max-width:100%;max-height:430px;object-fit:contain;border-radius:6px;margin:4px 0 7px}}.time{{text-align:right;font-size:10px;color:#687779;margin-top:3px}}.foot{{padding:10px;text-align:center;background:#fff4cf;font-size:11px;font-weight:800;color:#5d4210}}
{wechat_css}
{web_css}
</style></head><body class="{style} {tone}"><div class="frame"><header class="top">{avatar_html}<div class="head-main"><strong>{escape(str(buyer.get("name") or "Buyer"))}</strong></div>{toolbar}</header><div class="sub">{escape(str(data['country']))} · {escape(str(data['language']))} · {escape(str(data['timezone']))}</div><main class="chat">{''.join(body)}</main>{composer}</div></body></html>'''
