from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from uuid import uuid4

from .models import now_iso

MAIL_WIDTH = 1120
MAX_MAIL_MESSAGES = 20


def new_mail_message(*, sent_at: str = "", sender: str = "", recipient: str = "", body: str = "") -> dict:
    return {
        "id": uuid4().hex,
        "sender": sender,
        "recipient": recipient,
        "cc": "",
        "sent_at": sent_at or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "body": body,
    }


def new_mail_record() -> dict:
    start = datetime.now().replace(second=0, microsecond=0) - timedelta(hours=2)
    created = now_iso()
    return {
        "mail_id": uuid4().hex,
        "created_at": created,
        "updated_at": created,
        "subject": "产品资料与报价确认",
        "account": "sales@example.com",
        "folder": "收件箱",
        "messages": [
            new_mail_message(
                sent_at=start.strftime("%Y-%m-%d %H:%M"),
                sender="Camille Martin <buyer@example.com>",
                recipient="Alex Chen <sales@example.com>",
                body="您好，能否发来这款产品的资料和报价范围？\n期待您的回复。",
            ),
            new_mail_message(
                sent_at=(start + timedelta(minutes=35)).strftime("%Y-%m-%d %H:%M"),
                sender="Alex Chen <sales@example.com>",
                recipient="Camille Martin <buyer@example.com>",
                body="您好，感谢来信。\n我会整理产品资料，报价请以正式文件为准。",
            ),
        ],
    }


def validate_mail(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("邮件记录必须是 JSON 对象。")
    identifier = data.get("mail_id", "")
    if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
        raise ValueError("邮件记录 ID 无效。")
    for key, limit in (("subject", 200), ("account", 200), ("folder", 30)):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"邮件字段 {key} 不能为空或过长。")
    messages = data.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MAIL_MESSAGES:
        raise ValueError(f"邮件数量必须在 1–{MAX_MAIL_MESSAGES} 封之间。")
    seen = set()
    for index, message in enumerate(messages, 1):
        if not isinstance(message, dict):
            raise ValueError(f"第 {index} 封邮件格式无效。")
        message_id = message.get("id", "")
        if not isinstance(message_id, str) or len(message_id) != 32 or any(c not in "0123456789abcdef" for c in message_id) or message_id in seen:
            raise ValueError(f"第 {index} 封邮件 ID 无效或重复。")
        seen.add(message_id)
        for key, limit in (("sender", 300), ("recipient", 300), ("cc", 300), ("body", 20000)):
            value = message.get(key)
            if not isinstance(value, str) or len(value) > limit or (key in ("sender", "recipient") and not value.strip()):
                raise ValueError(f"第 {index} 封邮件的 {key} 无效。")
        try:
            datetime.strptime(message.get("sent_at", ""), "%Y-%m-%d %H:%M")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第 {index} 封邮件时间应为 YYYY-MM-DD HH:MM。") from exc
    return data


def render_mail_html(data: dict) -> str:
    subject = escape(data["subject"])
    account = escape(data["account"])
    folder = escape(data["folder"])
    inbox_class = "nav active" if data["folder"] == "收件箱" else "nav"
    sent_class = "nav active" if data["folder"] == "已发送" else "nav"
    cards = []
    for message in data["messages"]:
        sender = escape(message["sender"])
        recipient = escape(message["recipient"])
        cc = escape(message["cc"])
        sent_at = escape(message["sent_at"])
        body = escape(message["body"])
        initial = escape((message["sender"].strip() or "?")[:1].upper())
        cc_line = f'<div class="cc">抄送：{cc}</div>' if cc else ""
        cards.append(f'''<article class="message">
          <div class="avatar">{initial}</div>
          <div class="message-main"><div class="message-head"><strong>{sender}</strong><time>{sent_at}</time></div>
          <div class="recipient">收件人：{recipient}</div>{cc_line}<div class="body">{body}</div></div>
        </article>''')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{{box-sizing:border-box}}html,body{{margin:0;background:#edf2f5;color:#202124;font-family:Arial,"Microsoft YaHei",sans-serif}}
.frame{{width:{MAIL_WIDTH}px;min-height:690px;margin:0 auto;background:#f6f8fc}}
.top{{height:72px;display:flex;align-items:center;gap:30px;padding:0 30px;border-bottom:1px solid #e3e8ee}}
.brand{{width:218px;display:flex;align-items:center;gap:12px;font-size:21px;color:#5f6368;letter-spacing:-.5px}}
.brand-mark{{font-size:27px;font-weight:800;color:#d64b3e;letter-spacing:-5px;margin-right:5px}}
.search{{background:#eaf1fb;border-radius:22px;color:#68737f;padding:13px 20px;flex:1;max-width:650px;font-size:14px}}
.account{{margin-left:auto;background:#d6e7e1;color:#24574f;border-radius:50%;width:35px;height:35px;display:grid;place-items:center;font-weight:700}}
.workspace{{display:flex;min-height:618px}}.sidebar{{width:246px;flex:none;padding:22px 13px 25px 21px;color:#4b5963}}
.compose{{width:138px;padding:14px 19px;background:#dbeafb;border-radius:17px;font-weight:600;color:#2c4a66;margin-bottom:23px}}
.nav{{padding:10px 15px;border-radius:0 18px 18px 0;font-size:14px}}.nav.active{{background:#dce9fc;font-weight:700;color:#273b58}}
.mail-main{{flex:1;min-width:0;background:#fff;border-radius:17px 0 0 0;padding:0 32px 42px;box-shadow:-1px 0 3px #d9e2ea55}}
.toolbar{{height:56px;border-bottom:1px solid #ecedef;color:#6c747b;display:flex;align-items:center;gap:25px;font-size:16px}}
.simulation{{margin-left:auto;font-size:11px;font-weight:700;color:#7c4f23;background:#fff1d7;padding:6px 10px;border-radius:20px;letter-spacing:.04em}}
h1{{font-size:25px;line-height:1.35;font-weight:500;margin:25px 0 18px;overflow-wrap:anywhere}}
.folder{{display:inline-block;vertical-align:middle;margin-left:12px;background:#edf1f5;color:#667078;border-radius:4px;font-size:11px;padding:3px 7px}}
.message{{display:flex;gap:15px;border-top:1px solid #edf0f2;padding:21px 0 25px}}.message:first-of-type{{border-top:0}}
.avatar{{width:39px;height:39px;flex:none;border-radius:50%;display:grid;place-items:center;background:#56867b;color:white;font-weight:700}}
.message-main{{flex:1;min-width:0}}.message-head{{display:flex;justify-content:space-between;gap:16px;font-size:14px}}
.message-head strong{{overflow-wrap:anywhere}}time{{color:#647078;font-size:12px;white-space:nowrap}}
.recipient,.cc{{color:#70777d;font-size:12px;margin-top:4px;overflow-wrap:anywhere}}
.body{{margin-top:26px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.75;color:#273136}}
.footer{{padding:15px 32px;background:#fff;color:#8a9298;font-size:11px;text-align:right;border-top:1px solid #edf0f2}}
@media(max-width:800px){{.frame{{width:100%;min-height:0}}.top{{padding:0 17px}}.brand{{width:auto}}.search,.sidebar{{display:none}}
.mail-main{{border-radius:0;padding:0 16px 30px}}.message-head{{flex-direction:column;gap:4px}}time{{white-space:normal}}
.toolbar{{gap:15px}}.simulation{{font-size:9px}}.footer{{padding:12px 16px}}}}
</style></head><body><div class="frame"><header class="top"><div class="brand"><span class="brand-mark">M</span>Gmail</div><div class="search">⌕　搜索邮件</div><div class="account">{escape((data['account'] or '?')[:1].upper())}</div></header>
<div class="workspace"><aside class="sidebar"><div class="compose">✎　写邮件</div><div class="{inbox_class}">收件箱</div><div class="nav">已加星标</div><div class="{sent_class}">已发送</div><div class="nav">草稿</div></aside>
<main class="mail-main"><div class="toolbar"><span>‹</span><span>▣</span><span>↶</span><span>⋮</span><span class="simulation">模拟邮件记录 · DEMO</span></div>
<h1>{subject}<span class="folder">{folder}</span></h1>{''.join(cards)}</main></div><div class="footer">演示内容 · {account}</div></div></body></html>'''
