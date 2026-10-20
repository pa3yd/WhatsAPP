from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from .mail import new_mail_message, new_mail_record
from .models import new_conversation, new_message, normalize_positions, now_iso, uid
from .time_engine import assign_times

FIELD_LABELS = {
    "number": "PI 编号", "issue_date": "PI 日期", "valid_until": "有效期至",
    "seller_name": "卖方", "seller_address": "卖方地址", "seller_contact": "卖方联系人",
    "seller_email": "卖方邮箱", "seller_phone": "卖方电话", "seller_tax_id": "卖方税号/注册号",
    "buyer_name": "买方", "buyer_address": "买方地址", "buyer_contact": "买方联系人",
    "buyer_email": "买方邮箱", "buyer_phone": "买方电话", "buyer_tax_id": "买方税号/注册号",
    "currency": "币种", "incoterm": "贸易条款",
    "origin": "装运港/发货地", "destination": "目的港/收货地", "shipping_method": "运输方式",
    "payment_terms": "付款条款", "delivery_terms": "交期", "packing": "包装方式",
    "bank_name": "收款银行", "bank_address": "银行地址", "bank_account": "银行账号",
    "swift_code": "SWIFT/BIC", "beneficiary": "收款人",
    "freight": "运费", "insurance": "保险费", "discount": "折扣", "notes": "备注",
    "source_total": "总金额",
}
ITEM_LABELS = {"description": "品名", "model": "型号", "quantity": "数量", "unit": "单位", "unit_price": "单价"}
LEGACY_MAP = {
    "number": "number", "date": "issue_date", "seller": "seller_name", "buyer": "buyer_name",
    "currency": "currency", "incoterm": "incoterm", "payment": "payment_terms",
    "delivery": "delivery_terms", "shipping": "shipping_method", "total": "source_total",
}
ALIASES = {label.replace(" ", "").casefold(): key for key, label in FIELD_LABELS.items()}
ALIASES.update({
    "pi no": "number", "pi number": "number", "invoice no": "number",
    "invoice date": "issue_date", "seller": "seller_name", "buyer": "buyer_name",
    "product": "product", "产品与规格": "product", "quantity": "quantity",
    "unit price": "unit_price", "total": "source_total", "grand total": "source_total",
    "payment": "payment_terms", "delivery": "delivery_terms", "shipping": "shipping_method",
    "incoterm": "incoterm", "currency": "currency",
})


def new_item() -> dict:
    return {"id": uid(), "description": "", "model": "", "quantity": "", "unit": "pcs", "unit_price": ""}


def new_extra_term() -> dict:
    return {"id": uid(), "label": "", "value": ""}


def new_invoice(*, blank: bool = False) -> dict:
    created = now_iso()
    fields = {key: "" for key in FIELD_LABELS}
    if not blank:
        fields.update(issue_date=date.today().isoformat(), currency="USD", freight="0.00", insurance="0.00", discount="0.00")
    return {"invoice_id": uid(), "created_at": created, "updated_at": created,
            "fields": fields, "items": [new_item()], "extra_terms": [], "source_kind": "手工创建"}


def _decimal(value: str, label: str, *, positive: bool = False) -> Decimal:
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label}须为数字。") from exc
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError(f"{label}须为{'大于零' if positive else '非负'}数字。")
    return number


def invoice_totals(invoice: dict) -> tuple[list[Decimal], Decimal, Decimal]:
    amounts = []
    for index, item in enumerate(invoice["items"], 1):
        quantity = _decimal(item["quantity"], f"第 {index} 项数量", positive=True)
        price = _decimal(item["unit_price"], f"第 {index} 项单价")
        amounts.append(quantity * price)
    subtotal = sum(amounts, Decimal("0"))
    fields = invoice["fields"]
    freight = _decimal(fields["freight"] or "0", "运费")
    insurance = _decimal(fields["insurance"] or "0", "保险费")
    discount = _decimal(fields["discount"] or "0", "折扣")
    total = subtotal + freight + insurance - discount
    if total < 0:
        raise ValueError("折扣不能超过小计及附加费用。")
    return amounts, subtotal, total


def money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}"


def validate_invoice(invoice: dict, *, complete: bool = False) -> dict:
    if not isinstance(invoice, dict) or not isinstance(invoice.get("invoice_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", invoice["invoice_id"]):
        raise ValueError("PI 记录 ID 无效。")
    fields = invoice.get("fields")
    if not isinstance(fields, dict) or any(key not in fields or not isinstance(fields[key], str) or len(fields[key]) > 2000 for key in FIELD_LABELS):
        raise ValueError("PI 字段格式无效。")
    for key in ("issue_date", "valid_until"):
        if fields[key].strip():
            try:
                date.fromisoformat(fields[key])
            except ValueError as exc:
                raise ValueError(f"{FIELD_LABELS[key]}应为 YYYY-MM-DD。") from exc
    items = invoice.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError("PI 明细须有 1–50 项。")
    item_ids = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(r"[0-9a-f]{32}", item["id"]) or item["id"] in item_ids:
            raise ValueError(f"第 {index} 项明细 ID 无效或重复。")
        item_ids.add(item["id"])
        if any(key not in item or not isinstance(item[key], str) or len(item[key]) > 500 for key in ITEM_LABELS):
            raise ValueError(f"第 {index} 项明细格式无效。")
    extras = invoice.get("extra_terms")
    if not isinstance(extras, list) or len(extras) > 30:
        raise ValueError("附加条款不能超过 30 项。")
    extra_ids = set()
    for extra in extras:
        if not isinstance(extra, dict) or not isinstance(extra.get("id"), str) or not re.fullmatch(r"[0-9a-f]{32}", extra["id"]) or any(not isinstance(extra.get(key), str) or len(extra[key]) > 1000 for key in ("label", "value")):
            raise ValueError("附加条款格式无效。")
        if extra["id"] in extra_ids:
            raise ValueError("附加条款 ID 重复。")
        extra_ids.add(extra["id"])
    if complete:
        for key in ("number", "issue_date", "seller_name", "buyer_name", "currency"):
            if not fields[key].strip():
                raise ValueError(f"请填写{FIELD_LABELS[key]}。")
        for index, item in enumerate(items, 1):
            if not item["description"].strip():
                raise ValueError(f"请填写第 {index} 项品名。")
        invoice_totals(invoice)
    return invoice


def invoice_warnings(invoice: dict) -> list[str]:
    fields = invoice["fields"]
    recommended = ("seller_address", "buyer_address", "incoterm", "payment_terms", "delivery_terms")
    warnings = [f"待补：{FIELD_LABELS[key]}" for key in recommended if not fields[key].strip()]
    try:
        _, _, total = invoice_totals(invoice)
        if fields["source_total"].strip():
            try:
                source_total = _decimal(fields["source_total"].replace(fields["currency"], "").strip(), "原文总金额")
                if abs(total - source_total) > Decimal("0.01"):
                    warnings.append(f"原文总金额 {fields['source_total']} 与明细计算 {money(total)} 不一致，请核对。")
            except ValueError:
                warnings.append("原文总金额尚未解析为数字，请人工核对。")
    except ValueError as exc:
        warnings.append(str(exc))
    return warnings


def from_legacy_fields(fields: dict[str, str], *, source_kind: str) -> dict:
    invoice = new_invoice(blank=True)
    invoice["source_kind"] = source_kind
    target = invoice["fields"]
    for old, new in LEGACY_MAP.items():
        if isinstance(fields.get(old), str):
            target[new] = fields[old].strip()
    item = invoice["items"][0]
    for old, new in (("product", "description"), ("quantity", "quantity"), ("unit_price", "unit_price")):
        if isinstance(fields.get(old), str):
            item[new] = fields[old].strip()
    return invoice


def from_explicit_text(text: str, *, source_kind: str) -> tuple[dict, int]:
    invoice = new_invoice(blank=True)
    invoice["source_kind"] = source_kind
    matched = 0
    items: dict[int, dict] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([^:：]{1,50})\s*[:：]\s*(.*?)\s*$", line)
        if not match or not match.group(2):
            continue
        label, value = match.group(1).strip(), match.group(2).strip()
        if label.startswith("附加条款 "):
            invoice["extra_terms"].append({**new_extra_term(), "label": label.removeprefix("附加条款 ").strip(), "value": value})
            matched += 1
            continue
        item_match = re.fullmatch(r"(品名|型号|数量|单位|单价)\s*(\d{1,2})", label)
        if item_match:
            index = int(item_match.group(2))
            if 1 <= index <= 50:
                key = {name: code for code, name in ITEM_LABELS.items()}[item_match.group(1)]
                items.setdefault(index, new_item())[key] = value
                matched += 1
            continue
        key = ALIASES.get(label.replace(" ", "").casefold()) or ALIASES.get(label.casefold())
        if key in invoice["fields"]:
            invoice["fields"][key] = value
            matched += 1
        elif key in ("product", "quantity", "unit_price"):
            invoice["items"][0][{"product": "description", "quantity": "quantity", "unit_price": "unit_price"}[key]] = value
            matched += 1
    if items:
        invoice["items"] = [items[index] for index in sorted(items)]
    return invoice, matched


def from_chat(chat: dict) -> tuple[dict, int]:
    text = "\n".join(str(message.get("text") or "") for message in chat.get("messages", []))
    invoice, matched = from_explicit_text(text, source_kind="聊天记录候选")
    legacy = chat.get("pi", {}).get("fields", {})
    if isinstance(legacy, dict) and legacy:
        fallback = from_legacy_fields(legacy, source_kind="聊天记录候选")
        for key in FIELD_LABELS:
            if not invoice["fields"][key]:
                invoice["fields"][key] = fallback["fields"][key]
        for key in ITEM_LABELS:
            if not invoice["items"][0][key]:
                invoice["items"][0][key] = fallback["items"][0][key]
        matched += sum(bool(value) for value in legacy.values())
    return invoice, matched


def from_mail(mail: dict) -> tuple[dict, int]:
    text = "\n".join(str(message.get("body") or "") for message in mail.get("messages", []))
    return from_explicit_text(text, source_kind="邮件记录候选")


def summary_lines(invoice: dict) -> list[str]:
    fields = invoice["fields"]
    lines = [f"{label}: {fields[key]}" for key, label in FIELD_LABELS.items()
             if key != "source_total" and fields[key].strip()]
    for index, item in enumerate(invoice["items"], 1):
        lines += [f"{label} {index}: {item[key]}" for key, label in ITEM_LABELS.items() if item[key].strip()]
    for term in invoice["extra_terms"]:
        if term["label"].strip() and term["value"].strip():
            lines.append(f"附加条款 {term['label']}: {term['value']}")
    try:
        _, _, total = invoice_totals(invoice)
        lines.append(f"总金额: {fields['currency']} {money(total)}".strip())
    except ValueError:
        pass
    return lines


def to_chat_draft(invoice: dict, *, style: str = "classic") -> dict:
    validate_invoice(invoice)
    if style not in ("classic", "wechat"):
        raise ValueError("PI 聊天草稿仅支持 WhatsApp 或微信风格。")
    fields = invoice["fields"]
    chat = new_conversation()
    chat["render_settings"]["style"] = style
    chat["render_settings"]["width"] = 560 if style == "wechat" else 420
    chat["title"] = f"PI {fields['number'] or '待编号'} · 模拟沟通"
    chat["language"] = "中文"
    chat["participants"]["buyer"]["name"] = fields["buyer_name"] or "买方（待填写）"
    chat["participants"]["seller"]["name"] = fields["seller_name"] or "卖方（待填写）"
    chat["product"]["name"] = invoice["items"][0]["description"] or "PI 产品（待填写）"
    details = "\n".join(summary_lines(invoice)) or "PI 条款待填写。"
    chat["messages"] = [
        new_message("buyer", "您好，请一起核对这份形式发票的内容。"),
        new_message("seller", "以下是可编辑的 PI 讨论草稿，请逐项确认：\n" + details),
        new_message("buyer", "收到。付款、交期和金额请以核对后的正式文件为准。"),
    ]
    normalize_positions(chat)
    assign_times(chat)
    return chat


def to_mail_draft(invoice: dict) -> dict:
    validate_invoice(invoice)
    fields = invoice["fields"]
    mail = new_mail_record()
    mail["subject"] = f"PI {fields['number'] or '待编号'} · 形式发票条款核对（模拟）"
    mail["account"] = fields["seller_email"] or "demo@example.com"
    mail["folder"] = "已发送"
    mail["messages"] = [new_mail_message(
        sender=f"{fields['seller_name'] or '卖方（待填写）'} <{fields['seller_email']}>" if fields["seller_email"] else fields["seller_name"] or "卖方（待填写）",
        recipient=f"{fields['buyer_name'] or '买方（待填写）'} <{fields['buyer_email']}>" if fields["buyer_email"] else fields["buyer_name"] or "买方（待填写）",
        body="您好，\n以下是可编辑的形式发票条款草稿，请逐项核对：\n\n" + ("\n".join(summary_lines(invoice)) or "PI 条款待填写。") + "\n\n此邮件为模拟草稿，正式条款以人工确认的文件为准。",
    )]
    return mail
