from __future__ import annotations

import hashlib
import json

import streamlit as st

from .exporter import screenshot_html
from .invoice import (FIELD_LABELS, ITEM_LABELS, from_chat, from_legacy_fields, from_mail,
                      invoice_totals, invoice_warnings, money, new_extra_term, new_invoice,
                      new_item, to_chat_draft, to_mail_draft, validate_invoice)
from .invoice_render import INVOICE_WIDTH, export_invoice_pdf, render_invoice_html
from .pi_reader import extract_pi


def _fingerprint(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _reset_invoice(data: dict) -> None:
    st.session_state.invoice = data
    st.session_state.invoice_rev = st.session_state.get("invoice_rev", 0) + 1


def render_invoice_page(store, chat: dict, mail: dict, reset_chat, reset_mail) -> None:
    if "invoice" not in st.session_state:
        st.session_state.invoice = new_invoice()
        st.session_state.invoice_rev = 0
    invoice = st.session_state.invoice
    revision = st.session_state.invoice_rev
    fields = invoice["fields"]

    st.subheader("可编辑 PI 形式发票")
    st.caption("填写单据要素和商品明细，金额自动计算。PDF 与截图标明模拟草稿；正式报价和客户信息须人工核对。")
    with st.expander("从 PDF、聊天或邮件建立 PI 候选草稿"):
        uploaded_pdf = st.file_uploader("上传可复制文字的 PI PDF", type=["pdf"], key=f"invoice-pdf-{revision}")
        if uploaded_pdf and st.button("从 PDF 提取候选字段"):
            try:
                extracted, raw_text, pages = extract_pi(uploaded_pdf.getvalue())
                st.session_state.invoice_candidate = from_legacy_fields(extracted, source_kind="PDF 提取候选")
                st.session_state.invoice_candidate_raw = raw_text
                st.session_state.invoice_candidate_count = sum(bool(value) for value in extracted.values())
                st.success(f"已提取 {pages} 页，识别到 {st.session_state.invoice_candidate_count} 项候选字段。")
            except Exception as exc:
                st.error(str(exc))
        a, b = st.columns(2)
        if a.button("从当前微信/WhatsApp 聊天提取"):
            candidate, count = from_chat(chat)
            st.session_state.invoice_candidate = candidate
            st.session_state.invoice_candidate_count = count
            st.session_state.invoice_candidate_raw = "\n".join(message.get("text", "") for message in chat["messages"])
        if b.button("从当前邮件记录提取"):
            candidate, count = from_mail(mail)
            st.session_state.invoice_candidate = candidate
            st.session_state.invoice_candidate_count = count
            st.session_state.invoice_candidate_raw = "\n".join(message.get("body", "") for message in mail["messages"])
        imported_json = st.file_uploader("或导入 PI JSON", type=["json"], key=f"invoice-json-{revision}")
        if imported_json and st.button("验证并载入 PI JSON"):
            try:
                candidate = validate_invoice(json.loads(imported_json.getvalue().decode("utf-8")))
                _reset_invoice(candidate)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        candidate = st.session_state.get("invoice_candidate")
        if candidate:
            count = st.session_state.get("invoice_candidate_count", 0)
            st.info(f"来源：{candidate['source_kind']}；识别 {count} 处明确字段。以下是待核对草稿，空白项需要人工补齐。")
            with st.expander("核对来源原文与候选字段"):
                st.text_area("来源文字", st.session_state.get("invoice_candidate_raw", ""), height=170, disabled=True)
                st.json({"fields": {key: value for key, value in candidate["fields"].items() if value},
                         "items": candidate["items"]})
            if st.button("载入候选到 PI 编辑器"):
                _reset_invoice(candidate)
                st.session_state.pop("invoice_candidate", None)
                st.rerun()

    if st.button("新建空白 PI"):
        _reset_invoice(new_invoice())
        st.rerun()
    st.markdown("#### 基本信息")
    c1, c2, c3 = st.columns(3)
    fields["number"] = c1.text_input(FIELD_LABELS["number"], fields["number"], key=f"pi-{revision}-number")
    fields["issue_date"] = c2.text_input(FIELD_LABELS["issue_date"] + "（YYYY-MM-DD）", fields["issue_date"], key=f"pi-{revision}-date")
    fields["valid_until"] = c3.text_input(FIELD_LABELS["valid_until"] + "（可选）", fields["valid_until"], key=f"pi-{revision}-valid")
    with st.expander("买卖双方资料", expanded=True):
        for prefix, label in (("seller", "卖方"), ("buyer", "买方")):
            st.markdown(f"**{label}**")
            a, b = st.columns(2)
            for column, key in ((a, f"{prefix}_name"), (b, f"{prefix}_address")):
                fields[key] = column.text_input(FIELD_LABELS[key], fields[key], key=f"pi-{revision}-{key}")
            a, b, c = st.columns(3)
            keys = (f"{prefix}_contact", f"{prefix}_email", f"{prefix}_phone")
            for column, key in zip((a, b, c), keys):
                fields[key] = column.text_input(FIELD_LABELS[key], fields[key], key=f"pi-{revision}-{key}")
            fields[f"{prefix}_tax_id"] = st.text_input(FIELD_LABELS[f"{prefix}_tax_id"], fields[f"{prefix}_tax_id"], key=f"pi-{revision}-{prefix}-tax-id")

    st.markdown("#### 商品明细")
    for index, item in enumerate(invoice["items"]):
        with st.expander(f"明细 {index + 1:02d} · {item['description'] or '待填写品名'}", expanded=index == len(invoice["items"]) - 1):
            key = f"pi-{revision}-{item['id']}"
            a, b = st.columns(2)
            item["description"] = a.text_input("品名/描述", item["description"], key=f"{key}-description")
            item["model"] = b.text_input("型号/规格", item["model"], key=f"{key}-model")
            a, b, c = st.columns(3)
            item["quantity"] = a.text_input("数量", item["quantity"], key=f"{key}-quantity")
            item["unit"] = b.text_input("单位", item["unit"], key=f"{key}-unit")
            item["unit_price"] = c.text_input("单价", item["unit_price"], key=f"{key}-price")
            if st.button("删除此项明细", key=f"{key}-delete", disabled=len(invoice["items"]) == 1):
                invoice["items"].pop(index)
                _reset_invoice(invoice)
                st.rerun()
    if st.button("添加商品明细", disabled=len(invoice["items"]) >= 50):
        invoice["items"].append(new_item())
        _reset_invoice(invoice)
        st.rerun()

    with st.expander("贸易、运输与付款条款", expanded=True):
        keys = ("currency", "incoterm", "origin", "destination", "shipping_method",
                "payment_terms", "delivery_terms", "packing")
        for index in range(0, len(keys), 2):
            a, b = st.columns(2)
            for column, key in zip((a, b), keys[index:index + 2]):
                fields[key] = column.text_input(FIELD_LABELS[key], fields[key], key=f"pi-{revision}-{key}")
    with st.expander("金额调整与收款资料"):
        a, b, c = st.columns(3)
        for column, key in zip((a, b, c), ("freight", "insurance", "discount")):
            fields[key] = column.text_input(FIELD_LABELS[key], fields[key], key=f"pi-{revision}-{key}")
        for key in ("bank_name", "bank_address", "bank_account", "swift_code", "beneficiary"):
            fields[key] = st.text_input(FIELD_LABELS[key], fields[key], key=f"pi-{revision}-{key}")
        fields["source_total"] = st.text_input("原文总金额（仅核对，不参与计算）", fields["source_total"], key=f"pi-{revision}-source-total")
    with st.expander("附加条款与备注"):
        for index, term in enumerate(invoice["extra_terms"]):
            key = f"pi-{revision}-{term['id']}"
            a, b, c = st.columns([2, 4, 1])
            term["label"] = a.text_input("条款名称", term["label"], key=f"{key}-label")
            term["value"] = b.text_input("条款内容", term["value"], key=f"{key}-value")
            if c.button("删除", key=f"{key}-delete"):
                invoice["extra_terms"].pop(index)
                _reset_invoice(invoice)
                st.rerun()
        if st.button("添加附加条款", disabled=len(invoice["extra_terms"]) >= 30):
            invoice["extra_terms"].append(new_extra_term())
            _reset_invoice(invoice)
            st.rerun()
        fields["notes"] = st.text_area(FIELD_LABELS["notes"], fields["notes"], key=f"pi-{revision}-notes", height=100)

    try:
        _, subtotal, total = invoice_totals(invoice)
        st.metric("自动计算总金额", f"{fields['currency']} {money(total)}", help=f"商品小计 {money(subtotal)}，加运费、保险费并减折扣。")
    except ValueError as exc:
        st.info(f"金额待计算：{exc}")
    with st.expander("完整性与来源核对"):
        st.caption(f"来源：{invoice.get('source_kind', '手工创建')}。自由文本只识别明确标注的 PI 字段，其他内容不会自动填入正式条款。")
        for warning in invoice_warnings(invoice):
            st.warning(warning)

    st.subheader("单据预览")
    try:
        st.iframe(render_invoice_html(invoice), height=1050)
    except Exception as exc:
        st.error(str(exc))
    st.subheader("保存与导出")
    a, b, c = st.columns(3)
    if a.button("保存 PI 草稿"):
        try:
            _reset_invoice(store.save_invoice(invoice))
            st.success("PI 草稿已保存。")
        except Exception as exc:
            st.error(str(exc))
    if b.button("另存 PI 新版本"):
        try:
            _reset_invoice(store.save_invoice(invoice, new_version=True))
            st.success("PI 新版本已保存。")
        except Exception as exc:
            st.error(str(exc))
    c.download_button("下载 PI JSON", json.dumps(invoice, ensure_ascii=False, indent=2).encode("utf-8"),
                      file_name=f"pi_{invoice['invoice_id'][:8]}.json", mime="application/json")
    a, b = st.columns(2)
    if a.button("准备 PI PNG"):
        try:
            st.session_state.invoice_png = screenshot_html(render_invoice_html(invoice), INVOICE_WIDTH, scale=2)
            st.session_state.invoice_png_fingerprint = _fingerprint(invoice)
        except Exception as exc:
            st.error(str(exc))
    if b.button("准备 PI PDF", type="primary"):
        try:
            st.session_state.invoice_pdf = export_invoice_pdf(invoice)
            st.session_state.invoice_pdf_fingerprint = _fingerprint(invoice)
        except Exception as exc:
            st.error(str(exc))
    if st.session_state.get("invoice_png") and st.session_state.get("invoice_png_fingerprint") == _fingerprint(invoice):
        st.download_button("下载 PI PNG", st.session_state.invoice_png, file_name=f"pi_{invoice['invoice_id'][:8]}.png", mime="image/png")
    if st.session_state.get("invoice_pdf") and st.session_state.get("invoice_pdf_fingerprint") == _fingerprint(invoice):
        st.download_button("下载 PI PDF", st.session_state.invoice_pdf, file_name=f"pi_{invoice['invoice_id'][:8]}.pdf", mime="application/pdf")

    st.subheader("转换为可编辑沟通草稿")
    st.caption("从当前 PI 生成新的聊天与邮件草稿。载入目标编辑器后，可以继续增删和修改内容；不会自动覆盖已保存的记录。")
    chat_style = st.selectbox("聊天草稿界面", ["WhatsApp 风格", "微信风格"], key="invoice-chat-style")
    if st.button("生成聊天和邮件草稿"):
        try:
            st.session_state.invoice_chat_draft = to_chat_draft(invoice, style="wechat" if chat_style == "微信风格" else "classic")
            st.session_state.invoice_mail_draft = to_mail_draft(invoice)
            st.session_state.invoice_drafts_fingerprint = _fingerprint({"invoice": invoice, "style": chat_style})
        except Exception as exc:
            st.error(str(exc))
    if st.session_state.get("invoice_drafts_fingerprint") == _fingerprint({"invoice": invoice, "style": chat_style}):
        a, b = st.columns(2)
        if a.button("在聊天编辑器打开草稿"):
            reset_chat(st.session_state.invoice_chat_draft)
            st.session_state.nav_to = "单组聊天与编辑"
            st.rerun()
        if b.button("在邮件编辑器打开草稿"):
            reset_mail(st.session_state.invoice_mail_draft)
            st.session_state.nav_to = "邮件记录截图"
            st.rerun()

    st.subheader("已保存的 PI")
    for record in store.list_invoice_records():
        rid = record["id"]
        columns = st.columns([4, 1, 1, 1])
        columns[0].write(f"{record['title']} · {record['updated_at']} · {rid[:8]}")
        if columns[1].button("载入", key=f"load-invoice-{rid}"):
            try:
                _reset_invoice(store.load_invoice(rid))
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if columns[2].button("删除", key=f"ask-delete-invoice-{rid}"):
            st.session_state.invoice_delete_target = rid
        if st.session_state.get("invoice_delete_target") == rid:
            if columns[3].button("确认删除", key=f"confirm-delete-invoice-{rid}"):
                try:
                    store.delete_invoice(rid)
                    st.session_state.invoice_delete_target = None
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
