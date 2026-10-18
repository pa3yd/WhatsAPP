from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import streamlit as st

from chatbench.exporter import export_png, export_zip, safe_filename
from chatbench.generator import clone_for_batch, generate_ai, offline_sample, regenerate_one
from chatbench.models import keyword_warnings, new_conversation, new_message, normalize_positions, validate_conversation
from chatbench.renderer import render_html
from chatbench.storage import Store
from chatbench.time_engine import assign_times, parse_manual, timeline_warnings

st.set_page_config(page_title="模拟聊天工作台", page_icon="💬", layout="wide")
st.markdown("""<style>.block-container{padding-top:1.3rem}.stButton button{border-radius:8px}.small-note{color:#617478;font-size:.85rem}</style>""", unsafe_allow_html=True)
store = Store()


def alert_error(exc: Exception) -> None:
    st.error(str(exc))


def reset_editor(data: dict) -> None:
    st.session_state.chat = data
    st.session_state.editor_rev = st.session_state.get("editor_rev", 0) + 1


if "chat" not in st.session_state:
    initial = new_conversation()
    assign_times(initial)
    st.session_state.chat = initial
    st.session_state.editor_rev = 0
if "batch" not in st.session_state:
    st.session_state.batch = []
if "nav_to" in st.session_state:
    st.session_state.page = st.session_state.pop("nav_to")

data = st.session_state.chat
revision = st.session_state.editor_rev
normalize_positions(data)


def fingerprint(chat: dict) -> str:
    return hashlib.sha256(json.dumps(chat, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def comma_list(value: str) -> list[str]:
    return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]


def upload_widget(label: str, key: str, assign) -> None:
    uploaded = st.file_uploader(label, type=["png", "jpg", "jpeg", "webp"], key=f"{revision}-{key}")
    if uploaded and st.button("保存并使用图片", key=f"save-{revision}-{key}"):
        try:
            assign(store.save_image(uploaded.getvalue()))
            st.rerun()
        except Exception as exc:
            alert_error(exc)


def preview(chat: dict, *, height: int | None = None) -> None:
    try:
        # All dynamic text is escaped by renderer; images come only from validated local assets.
        st.iframe(render_html(chat, store), height=height or "content")
    except Exception as exc:
        alert_error(exc)


st.title("模拟聊天工作台")
st.caption("所有人物、消息与时间均为模拟内容；预览和导出固定显示模拟标识。")
page = st.sidebar.radio("工作区", ["单组聊天与编辑", "批量生成", "历史与模板"], key="page")
st.sidebar.caption("本地数据：D:\\WhatsAPP\\data")

if page == "单组聊天与编辑":
    left, right = st.columns([1.08, 1], gap="large")
    with left:
        st.subheader("场景与人物")
        data["title"] = st.text_input("标题", data["title"], key=f"{revision}-title")
        c1, c2 = st.columns(2)
        data["country"] = c1.text_input("国家", data["country"], key=f"{revision}-country")
        data["language"] = c2.text_input("聊天语言", data["language"], key=f"{revision}-language")
        data["timezone"] = c1.text_input("时区（IANA）", data["timezone"], key=f"{revision}-zone")
        if data["country"].strip() == "法国" and data["timezone"] != "Europe/Paris":
            st.warning("法国场景当前使用非 Europe/Paris 时区；这是允许的显式选择。")
            if st.button("切换为 Europe/Paris"):
                data["timezone"] = "Europe/Paris"
                reset_editor(data)
                st.rerun()
        data["tone"] = c2.text_input("语气", data["tone"], key=f"{revision}-tone")
        data["goal"] = st.text_input("对话目标", data["goal"], key=f"{revision}-goal")
        data["allow_details"] = st.checkbox("允许 AI 补充合理细节", data["allow_details"], key=f"{revision}-details")
        for person_id, heading in (("buyer", "买家"), ("seller", "卖家")):
            with st.expander(f"{heading}资料", expanded=False):
                person = data["participants"][person_id]
                person["name"] = st.text_input(f"{heading}姓名", person["name"], key=f"{revision}-{person_id}-name")
                person["role"] = st.text_input(f"{heading}职位", person["role"], key=f"{revision}-{person_id}-role")
                person["company"] = st.text_input(f"{heading}公司", person["company"], key=f"{revision}-{person_id}-company")
                person["region"] = st.text_input(f"{heading}国家/地区", person["region"], key=f"{revision}-{person_id}-region")
                person["style"] = st.text_input(f"{heading}表达风格", person["style"], key=f"{revision}-{person_id}-style")
                if person.get("avatar_id"):
                    try:
                        st.image(str(store.image_path(person["avatar_id"])), width=75)
                    except ValueError as exc:
                        alert_error(exc)
                upload_widget(f"上传{heading}虚构头像", f"{person_id}-avatar", lambda asset, p=person: p.update(avatar_id=asset))
        st.subheader("产品与关键词")
        product = data["product"]
        product["name"] = st.text_input("产品名称", product["name"], key=f"{revision}-product")
        p1, p2 = st.columns(2)
        product["brand"] = p1.text_input("品牌（可选）", product["brand"], key=f"{revision}-brand")
        product["model"] = p2.text_input("型号（可选）", product["model"], key=f"{revision}-model")
        product["facts"] = st.text_area("关键产品信息（人工确认）", product["facts"], key=f"{revision}-facts", height=75)
        required = st.text_input("必须出现的关键词（逗号分隔）", ", ".join(data["keywords"]["required"]), key=f"{revision}-required")
        forbidden = st.text_input("禁止出现的关键词（逗号分隔）", ", ".join(data["keywords"]["forbidden"]), key=f"{revision}-forbidden")
        data["keywords"] = {"required": comma_list(required), "forbidden": comma_list(forbidden)}
        upload_widget("上传产品图片（可逐张添加）", "product-image", lambda asset: product["image_ids"].append(asset))
        if product["image_ids"]:
            st.caption(f"已保存 {len(product['image_ids'])} 张产品图片，可在具体消息中插入。")
        st.subheader("时间规则")
        rules = data["time_rules"]
        rules.setdefault("end_day_offset", 0)
        rules.setdefault("type_intervals", {})
        rules["mode"] = st.selectbox("时间模式", ["mixed", "auto", "manual"], index=["mixed", "auto", "manual"].index(rules["mode"]), format_func=lambda x: {"mixed": "混合", "auto": "自动", "manual": "全部手动"}[x], key=f"{revision}-mode")
        rules["preset"] = st.selectbox("回复节奏", ["正常回复", "快速回复", "延迟回复", "跨日回复", "完全自定义"], index=["正常回复", "快速回复", "延迟回复", "跨日回复", "完全自定义"].index(rules["preset"]), key=f"{revision}-preset")
        if st.button("采用节奏推荐范围"):
            intervals = {"正常回复": (5, 30), "快速回复": (1, 5), "延迟回复": (30, 180), "跨日回复": (60, 720), "完全自定义": (rules["min_minutes"], rules["max_minutes"])}
            rules["min_minutes"], rules["max_minutes"] = intervals[rules["preset"]]
            rules["end_day_offset"] = 1 if rules["preset"] == "跨日回复" else 0
            reset_editor(data)
            st.rerun()
        data["conversation_date"] = st.date_input("对话日期", date.fromisoformat(data["conversation_date"]), key=f"{revision}-date").isoformat()
        t1, t2 = st.columns(2)
        rules["start"] = t1.time_input("开始时间", time.fromisoformat(rules["start"]), step=60, key=f"{revision}-start").strftime("%H:%M")
        rules["end"] = t2.time_input("结束时间", time.fromisoformat(rules["end"]), step=60, key=f"{revision}-end").strftime("%H:%M")
        rules["end_day_offset"] = int(st.number_input("结束日期偏移（天）", min_value=0, max_value=7, value=int(rules["end_day_offset"]), key=f"{revision}-day-offset"))
        rules["min_minutes"] = int(t1.number_input("最小间隔（分钟）", min_value=0, value=int(rules["min_minutes"]), key=f"{revision}-min"))
        rules["max_minutes"] = int(t2.number_input("最大间隔（分钟）", min_value=0, value=int(rules["max_minutes"]), key=f"{revision}-max"))
        with st.expander("按消息类型覆盖间隔"):
            for message_type, caption in (("text", "纯文本"), ("image", "纯图片"), ("image_text", "图片加文字")):
                custom = message_type in rules["type_intervals"]
                enabled = st.checkbox(f"为{caption}单独设置", value=custom, key=f"{revision}-override-{message_type}")
                if enabled:
                    current = rules["type_intervals"].get(message_type, {"min_minutes": rules["min_minutes"], "max_minutes": rules["max_minutes"]})
                    x1, x2 = st.columns(2)
                    low = int(x1.number_input(f"{caption}最小分钟", min_value=0, value=int(current["min_minutes"]), key=f"{revision}-type-min-{message_type}"))
                    high = int(x2.number_input(f"{caption}最大分钟", min_value=0, value=int(current["max_minutes"]), key=f"{revision}-type-max-{message_type}"))
                    rules["type_intervals"][message_type] = {"min_minutes": low, "max_minutes": high}
                else:
                    rules["type_intervals"].pop(message_type, None)
        if st.button("重新计算自动时间"):
            try:
                assign_times(data)
                st.rerun()
            except Exception as exc:
                alert_error(exc)
        if st.button("明确覆盖所有人工时间并重算"):
            try:
                assign_times(data, recalculate_manual=True)
                st.rerun()
            except Exception as exc:
                alert_error(exc)
        st.subheader("创建对话")
        count = st.number_input("消息数量", min_value=1, max_value=100, value=len(data["messages"]), key=f"{revision}-count")
        mode = st.radio("生成方式", ["完全手动", "离线示例", "AI 生成"], horizontal=True, key=f"{revision}-generation")
        if st.button("创建/重新生成整组", type="primary"):
            try:
                draft = copy.deepcopy(data)
                if mode == "AI 生成":
                    generate_ai(draft, int(count))
                elif mode == "离线示例":
                    offline_sample(draft, int(count))
                else:
                    draft["messages"] = [new_message("buyer" if i % 2 == 0 else "seller") for i in range(int(count))]
                    if rules["mode"] != "manual":
                        assign_times(draft)
                reset_editor(draft)
                st.rerun()
            except Exception as exc:
                alert_error(exc)
        st.caption("整组重新生成会替换当前消息；建议先保存当前版本。AI 功能需另行配置密钥。")
    try:
        display_zone = ZoneInfo(data["timezone"])
    except Exception:
        display_zone = ZoneInfo("UTC")
        st.error("时区无效，请输入 IANA 时区名称，例如 Europe/Rome。")
    with right:
        st.subheader("实时预览")
        preview_slot = st.empty()
        warnings_slot = st.empty()
        st.subheader("保存与导出")
        s1, s2, s3 = st.columns(3)
        if s1.button("保存聊天"):
            try:
                reset_editor(store.save(data))
                st.success("已保存到本地历史记录。")
            except Exception as exc:
                alert_error(exc)
        if s2.button("另存新版本"):
            try:
                reset_editor(store.save(data, new_version=True))
                st.success("新版本已保存。")
            except Exception as exc:
                alert_error(exc)
        if s3.button("保存为模板"):
            try:
                store.save(data, template=True)
                st.success("模板已保存。")
            except Exception as exc:
                alert_error(exc)
        st.download_button("下载 JSON", json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), file_name=f"chat_{data['conversation_id'][:8]}.json", mime="application/json")
        if st.button("准备高清 PNG"):
            try:
                st.session_state.png = export_png(data, store)
                st.session_state.png_name = safe_filename(data["title"], data["conversation_id"])
                st.session_state.png_fingerprint = fingerprint(data)
            except Exception as exc:
                alert_error(exc)
        if st.session_state.get("png") and st.session_state.get("png_fingerprint") == fingerprint(data):
            st.download_button("下载高清 PNG", st.session_state.png, file_name=st.session_state.png_name, mime="image/png")
    st.divider()
    st.subheader("消息编辑器与时间轴")
    st.caption("调整顺序保留原时间；时间冲突由提醒指出。每条人工时间和锁定消息不会被自动重算覆盖。")
    for index, msg in enumerate(data["messages"]):
        stamp = msg.get("timestamp")
        display_stamp = datetime.fromisoformat(stamp).astimezone(display_zone).isoformat(timespec="minutes") if stamp else None
        previous = data["messages"][index - 1].get("timestamp") if index else None
        gap = ""
        if stamp and previous:
            gap = f" · 间隔 {(datetime.fromisoformat(stamp) - datetime.fromisoformat(previous)).total_seconds()/60:g} 分钟"
        summary = (msg.get("text") or "（空消息）").replace("\n", " ")[:42]
        badge = "📎" if msg.get("asset_id") else ""
        with st.expander(f"{index+1:02d} · {msg['sender_id']} · {display_stamp or '未设置时间'}{gap} · {summary} {badge}"):
            key = f"{revision}-{msg['id']}"
            msg["sender_id"] = st.selectbox("发送方", ["buyer", "seller"], index=["buyer", "seller"].index(msg["sender_id"]), key=key+"-sender", on_change=lambda m=msg, k=key+"-sender": m.update(sender_id=st.session_state[k]))
            def sync_text(m=msg, k=key+"-text"):
                m["text"] = st.session_state[k]
                m["type"] = "image_text" if m.get("asset_id") and m["text"] else "image" if m.get("asset_id") else "text"
            msg["text"] = st.text_area("消息文本", msg.get("text", ""), key=key+"-text", on_change=sync_text)
            msg["locked"] = st.checkbox("锁定，不允许 AI 修改", bool(msg.get("locked")), key=key+"-lock", on_change=lambda m=msg, k=key+"-lock": m.update(locked=st.session_state[k]))
            choices = ["无图片"] + [f"图片 {i+1} · {asset[:8]}" for i, asset in enumerate(product["image_ids"])]
            current_asset = msg.get("asset_id")
            selected = product["image_ids"].index(current_asset) + 1 if current_asset in product["image_ids"] else 0
            def sync_asset(m=msg, k=key+"-asset"):
                choice = st.session_state[k]
                m["asset_id"] = product["image_ids"][choice-1] if choice else None
                m["type"] = "image_text" if m["asset_id"] and m["text"] else "image" if m["asset_id"] else "text"
            image_index = st.selectbox("图片附件", range(len(choices)), index=selected, format_func=lambda i: choices[i], key=key+"-asset", on_change=sync_asset)
            msg["asset_id"] = product["image_ids"][image_index-1] if image_index else None
            msg["type"] = "image_text" if msg["asset_id"] and msg["text"] else "image" if msg["asset_id"] else "text"
            if msg["asset_id"]:
                st.image(str(store.image_path(msg["asset_id"])), width=180)
            local = datetime.fromisoformat(stamp).astimezone(display_zone) if stamp else datetime.fromisoformat(data["conversation_date"]+"T09:00:00")
            mc1, mc2, mc3 = st.columns([1, 1, 1])
            chosen_date = mc1.date_input("消息日期", local.date(), key=key+"-day")
            chosen_time = mc2.time_input("小时与分钟", local.time().replace(second=0, microsecond=0), step=60, key=key+"-clock")
            if mc3.button("应用人工时间", key=key+"-apply"):
                try:
                    msg["timestamp"] = parse_manual(chosen_date, chosen_time, data["timezone"])
                    msg["manual_time"] = True
                    st.rerun()
                except Exception as exc:
                    alert_error(exc)
            st.caption("时间来源：" + ("人工固定" if msg.get("manual_time") else "自动分配"))
            actions = st.columns(6)
            if actions[0].button("上移", key=key+"-up", disabled=index==0):
                data["messages"][index-1], data["messages"][index] = data["messages"][index], data["messages"][index-1]
                normalize_positions(data)
                reset_editor(data); st.rerun()
            if actions[1].button("下移", key=key+"-down", disabled=index==len(data["messages"])-1):
                data["messages"][index+1], data["messages"][index] = data["messages"][index], data["messages"][index+1]
                normalize_positions(data)
                reset_editor(data); st.rerun()
            if actions[2].button("复制", key=key+"-copy"):
                clone = copy.deepcopy(msg); clone["id"] = new_message()["id"]
                data["messages"].insert(index+1, clone); normalize_positions(data); reset_editor(data); st.rerun()
            if actions[3].button("下方新增", key=key+"-add"):
                data["messages"].insert(index+1, new_message(msg["sender_id"])); normalize_positions(data); reset_editor(data); st.rerun()
            if actions[4].button("删除", key=key+"-delete"):
                data["messages"].pop(index); normalize_positions(data); reset_editor(data); st.rerun()
            if actions[5].button("AI 重写", key=key+"-regen", disabled=msg.get("locked", False)):
                try:
                    regenerate_one(data, msg["id"]); reset_editor(data); st.rerun()
                except Exception as exc:
                    alert_error(exc)
    with preview_slot.container():
        preview(data)
    with warnings_slot.container():
        try:
            for warning in keyword_warnings(data) + timeline_warnings(data):
                st.warning(warning)
        except Exception as exc:
            alert_error(exc)

elif page == "批量生成":
    st.subheader("批量任务")
    st.caption("无密钥时批量创建可编辑的多语言离线示例。配置密钥后可逐组使用 AI 生成。")
    defaults = [{"国家": "法国", "语言": "法语", "时区": "Europe/Rome", "买家": "Camille Martin", "卖家": "Alex Chen", "买家身份": "采购经理", "卖家身份": "销售代表", "产品": "手机充电器", "必需词": "", "禁用词": "", "开始": "09:00", "结束": "16:30", "跨日天数": 0, "最小间隔": 5, "最大间隔": 30, "数量": 10},
                {"国家": "德国", "语言": "德语", "时区": "Europe/Berlin", "买家": "Lena Weber", "卖家": "Alex Chen", "买家身份": "采购经理", "卖家身份": "销售代表", "产品": "手机充电器", "必需词": "", "禁用词": "", "开始": "09:00", "结束": "16:30", "跨日天数": 0, "最小间隔": 5, "最大间隔": 30, "数量": 10}]
    rows = st.data_editor(defaults, num_rows="dynamic", width="stretch", key="batch-config")
    st.caption("各组可上传独立的虚构头像与产品图片；没有上传时沿用单组场景资源。")
    for row_index, row in enumerate(rows):
        with st.expander(f"任务 {row_index+1} 的图片资源"):
            st.file_uploader("买家头像", type=["png", "jpg", "jpeg", "webp"], key=f"batch-buyer-{row_index}")
            st.file_uploader("卖家头像", type=["png", "jpg", "jpeg", "webp"], key=f"batch-seller-{row_index}")
            st.file_uploader("产品图片（可多张）", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key=f"batch-product-{row_index}")

    def build_batch(row: dict, row_index: int, assets: dict | None = None) -> tuple[dict, dict]:
        resources = dict(assets or {})
        if not assets:
            for role in ("buyer", "seller"):
                upload = st.session_state.get(f"batch-{role}-{row_index}")
                if upload:
                    resources[role] = store.save_image(upload.getvalue())
            product_uploads = st.session_state.get(f"batch-product-{row_index}") or []
            resources["products"] = [store.save_image(upload.getvalue()) for upload in product_uploads]
        draft = copy.deepcopy(data)
        draft["product"]["name"] = str(row["产品"])
        draft["keywords"] = {"required": comma_list(str(row["必需词"])), "forbidden": comma_list(str(row["禁用词"]))}
        draft["time_rules"].update(start=str(row["开始"]), end=str(row["结束"]), end_day_offset=int(row["跨日天数"]), min_minutes=int(row["最小间隔"]), max_minutes=int(row["最大间隔"]), mode="mixed")
        chat = clone_for_batch(draft, country=str(row["国家"]), language=str(row["语言"]), timezone=str(row["时区"]), buyer=str(row["买家"]), seller=str(row["卖家"]), count=int(row["数量"]))
        for role in ("buyer", "seller"):
            chat["participants"][role]["role"] = str(row["买家身份"] if role == "buyer" else row["卖家身份"])
            if resources.get(role):
                chat["participants"][role]["avatar_id"] = resources[role]
        chat["product"]["image_ids"].extend(resources.get("products", []))
        return chat, resources
    batch_mode = st.radio("批量内容方式", ["离线示例", "AI 生成"], horizontal=True)
    if st.button("运行批量任务", type="primary"):
        st.session_state.batch = []
        st.session_state.pop("batch_zip", None)
        st.session_state.pop("batch_zip_errors", None)
        for row in rows:
            entry = {"config": row, "status": "处理中", "error": ""}
            st.session_state.batch.append(entry)
            try:
                chat, resources = build_batch(row, len(st.session_state.batch)-1)
                entry["assets"] = resources
                if batch_mode == "AI 生成":
                    generate_ai(chat, int(row["数量"]))
                validate_conversation(chat)
                entry.update(status="成功", data=chat)
            except Exception as exc:
                entry.update(status="失败", error=str(exc))
        st.rerun()
    successful = []
    for i, entry in enumerate(st.session_state.batch):
        st.markdown(f"**任务 {i+1} · {entry['config'].get('国家','')} · {entry['status']}**")
        if entry["status"] == "失败":
            st.error(entry["error"])
            if st.button("重试此组", key=f"retry-{i}"):
                row = entry["config"]
                try:
                    chat, resources = build_batch(row, i, entry.get("assets"))
                    entry["assets"] = resources
                    if batch_mode == "AI 生成": generate_ai(chat, int(row["数量"]))
                    entry.update(status="成功", data=chat, error="")
                    st.rerun()
                except Exception as exc:
                    entry["error"] = str(exc)
            continue
        chat = entry["data"]
        successful.append(entry)
        with st.expander("预览此组"):
            preview(chat, height=750)
        a, b, c, d = st.columns(4)
        if a.button("转入编辑器", key=f"edit-batch-{i}"):
            reset_editor(chat); st.session_state.nav_to = "单组聊天与编辑"; st.rerun()
        if b.button("重新生成此组", key=f"regen-batch-{i}"):
            try:
                draft = copy.deepcopy(chat)
                if batch_mode == "AI 生成": generate_ai(draft, len(chat["messages"]))
                else: offline_sample(draft, len(chat["messages"]))
                entry["data"] = draft; st.rerun()
            except Exception as exc: alert_error(exc)
        if c.button("保存 JSON", key=f"save-batch-{i}"):
            try: store.save(chat); st.success("已保存。")
            except Exception as exc: alert_error(exc)
        if d.button("准备 PNG", key=f"png-batch-{i}"):
            try: entry["png"] = export_png(chat, store); st.rerun()
            except Exception as exc: alert_error(exc)
        if entry.get("png"):
            st.download_button("下载此组 PNG", entry["png"], file_name=safe_filename(chat["title"], chat["conversation_id"]), mime="image/png", key=f"download-batch-{i}")
    if successful and st.button("准备全部成功 PNG 的 ZIP"):
        archive, errors = export_zip(successful, store)
        st.session_state.batch_zip = archive
        st.session_state.batch_zip_errors = errors
    if st.session_state.get("batch_zip"):
        st.download_button("下载批量 ZIP", st.session_state.batch_zip, file_name="simulated_chats.zip", mime="application/zip")
        for identifier, error in st.session_state.get("batch_zip_errors", {}).items():
            st.error(f"{identifier[:8]} 导出失败：{error}")

else:
    st.subheader("历史记录与模板")
    uploaded_json = st.file_uploader("导入聊天 JSON", type="json")
    if uploaded_json and st.button("验证并载入 JSON"):
        try:
            incoming = validate_conversation(json.loads(uploaded_json.getvalue().decode("utf-8")))
            reset_editor(incoming); st.session_state.nav_to = "单组聊天与编辑"; st.rerun()
        except Exception as exc: alert_error(exc)
    for template in (False, True):
        st.markdown("### " + ("模板" if template else "历史记录"))
        for record in store.list_records(template=template):
            rid = record["id"]
            cols = st.columns([4, 1, 1, 1])
            cols[0].write(f"{record['title']} · {record['updated_at']} · {rid[:8]}")
            if cols[1].button("载入", key=f"load-{template}-{rid}"):
                try:
                    reset_editor(store.load(rid, template=template)); st.session_state.nav_to = "单组聊天与编辑"; st.rerun()
                except Exception as exc: alert_error(exc)
            if cols[2].button("删除", key=f"ask-delete-{template}-{rid}"):
                st.session_state.delete_target = (template, rid)
            if st.session_state.get("delete_target") == (template, rid):
                if cols[3].button("确认删除", key=f"confirm-{template}-{rid}"):
                    try:
                        store.delete(rid, template=template); st.session_state.delete_target = None; st.rerun()
                    except Exception as exc: alert_error(exc)
