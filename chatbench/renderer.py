from __future__ import annotations

import base64
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .storage import Store

LABEL = "SIMULATED CHAT — FOR TRAINING AND DEMONSTRATION"


def _image(store: Store, asset_id: str | None) -> str:
    if not asset_id:
        return ""
    raw = store.image_path(asset_id).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def render_html(data: dict, store: Store) -> str:
    buyer = data["participants"]["buyer"]
    seller = data["participants"]["seller"]
    title = escape(str(data["title"]))
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
        body.append(f'<div class="row {side}"><div class="bubble"><div class="sender">{name}</div>{attachment}<div class="text">{message}</div><div class="time">{escape(clock)}</div></div></div>')
    width = max(420, min(1000, int(data.get("render_settings", {}).get("width", 620))))
    return f'''<!doctype html><html lang="{escape(str(data.get("language", "en")))}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{{box-sizing:border-box}}html,body{{margin:0;padding:0;background:#e9e7e1;color:#18272b;font-family:Arial,"Noto Sans",sans-serif}}.frame{{width:{width}px;margin:auto;background:#efeae2;min-height:420px;box-shadow:0 4px 20px #0002}}.top{{background:#1c6662;color:white;padding:13px 18px;display:flex;align-items:center;gap:12px}}.avatar{{height:42px;width:42px;border-radius:50%;object-fit:cover;display:inline-flex;align-items:center;justify-content:center;background:#c9dcda;color:#134a46;font-weight:700}}.head-main{{min-width:0}}.head-main strong{{display:block;font-size:16px}}.head-main small{{opacity:.84}}.notice{{background:#fff4cf;color:#5d4210;text-align:center;padding:9px 12px;font-weight:800;font-size:12px;letter-spacing:.4px;border-bottom:2px solid #dba530}}.sub{{text-align:center;font-size:12px;padding:8px;color:#59666a}}.chat{{padding:12px 17px 25px;background-color:#e8e3d9;background-image:radial-gradient(#ffffff55 1px,transparent 1px);background-size:22px 22px}}.day{{width:max-content;margin:11px auto;padding:5px 10px;border-radius:7px;background:#e0f0ed;font-size:11px;color:#44615f}}.row{{display:flex;margin:8px 0}}.out{{justify-content:flex-end}}.bubble{{max-width:79%;min-width:110px;padding:8px 10px 5px;border-radius:9px;background:white;box-shadow:0 1px 2px #0002;overflow-wrap:anywhere}}.out .bubble{{background:#d6f2cf}}.sender{{font-size:12px;font-weight:bold;color:#327271;margin-bottom:3px}}.out .sender{{color:#4b7050}}.text{{white-space:pre-wrap;font-size:14px;line-height:1.45}}.attachment{{display:block;max-width:100%;max-height:430px;object-fit:contain;border-radius:6px;margin:4px 0 7px}}.time{{text-align:right;font-size:10px;color:#687779;margin-top:3px}}.foot{{padding:10px;text-align:center;background:#fff4cf;font-size:11px;font-weight:800;color:#5d4210}}
</style></head><body><div class="frame"><header class="top">{avatar_html}<div class="head-main"><strong>{escape(str(buyer.get("name") or "Buyer"))}</strong><small>{title} · 虚构人物与场景</small></div></header><div class="notice">{LABEL}</div><div class="sub">{escape(str(data['country']))} · {escape(str(data['language']))} · {escape(str(data['timezone']))}</div><main class="chat">{''.join(body)}</main><footer class="foot">{LABEL}</footer></div></body></html>'''
