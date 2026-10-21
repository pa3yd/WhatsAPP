from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import streamlit as st

from chatbench.exporter import export_png, export_zip, safe_filename, screenshot_html
from chatbench.generator import clone_for_batch, generate_ai, offline_sample, pi_discussion, regenerate_one
from chatbench import mail as mail_renderer
from chatbench.mail import MAIL_WIDTH, MAX_MAIL_MESSAGES, new_mail_message, new_mail_record, validate_mail
from chatbench.invoice_ui import render_invoice_page
from chatbench.pi_reader import FIELD_LABELS, extract_pi
from chatbench.models import keyword_warnings, new_conversation, new_group_member, new_message, normalize_positions, sender_options, validate_conversation
from chatbench.renderer import render_header_preview_html, render_html
from chatbench.storage import Store
from chatbench.time_engine import assign_times, parse_manual, timeline_warnings

st.set_page_config(page_title="模拟聊天工作台", page_icon="💬", layout="wide")
st.markdown("""<style>
:root {
  --surface: #ffffff;
  --canvas: #f4f7f6;
  --ink: #233634;
  --muted: #71817e;
  --line: #e3eae7;
  --brand: #24756d;
  --brand-dark: #195e58;
}
.stApp { background: var(--canvas); color: var(--ink); }
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 1500px; padding-top: 1.8rem; padding-bottom: 3rem; }
h1, h2, h3 { color: var(--ink); letter-spacing: -.02em; }
h1 { font-size: 2rem !important; font-weight: 700 !important; margin-bottom: .2rem !important; }
h2 { font-size: 1.35rem !important; font-weight: 650 !important; }
h3 { font-size: 1.05rem !important; font-weight: 650 !important; }
.block-container > div > div > div > div[data-testid="stCaptionContainer"] { color: var(--muted); }
[data-testid="stSidebar"] { background: #edf3f1; border-right: 1px solid var(--line); }
[data-testid="stSidebar"] > div { padding-top: 1.25rem; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: var(--muted); }
[data-testid="stRadio"] [role="radiogroup"] { gap: .4rem; }
[data-testid="stRadio"] [role="radiogroup"] label {
  border: 1px solid transparent; border-radius: 9px; padding: .45rem .65rem;
  transition: background .15s ease, border-color .15s ease;
}
[data-testid="stRadio"] [role="radiogroup"] label:hover { background: #e2eeea; border-color: #d2e3de; }
[data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) { background: #dcece7; border-color: #c7ded6; }
[data-baseweb="input"] > div, [data-baseweb="textarea"] > div, [data-baseweb="select"] > div {
  border-color: #d7e1dd; border-radius: 8px; background: var(--surface);
}
[data-baseweb="input"] > div:focus-within, [data-baseweb="textarea"] > div:focus-within,
[data-baseweb="select"] > div:focus-within { border-color: var(--brand); box-shadow: 0 0 0 1px var(--brand); }
.stButton button, .stDownloadButton button { border-radius: 8px; font-weight: 600; transition: all .15s ease; }
.stButton button[kind="primary"] { background: var(--brand); border-color: var(--brand); }
.stButton button[kind="primary"]:hover { background: var(--brand-dark); border-color: var(--brand-dark); }
.stButton button:not([kind="primary"]), .stDownloadButton button { border-color: #d5e0dc; color: #31534e; background: var(--surface); }
.stButton button:not([kind="primary"]):hover, .stDownloadButton button:hover { border-color: #9bbdb3; color: var(--brand-dark); }
[data-testid="stExpander"] { border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
[data-testid="stAlert"] { border-radius: 9px; }
hr { border-color: var(--line); }
.small-note { color: var(--muted); font-size: .85rem; }
@media (max-width: 700px) {
  .block-container { padding: 1rem 1rem 2rem; }
  h1 { font-size: 1.65rem !important; }
}
</style>""", unsafe_allow_html=True)
store = Store()

TIMEZONE_CHOICES = {
    "Asia/Shanghai": "北京时间（Asia/Shanghai）",
    "Europe/Paris": "巴黎时间（Europe/Paris）",
    "Europe/Rome": "罗马时间（Europe/Rome）",
    "Europe/Berlin": "柏林时间（Europe/Berlin）",
    "Europe/London": "伦敦时间（Europe/London）",
    "America/New_York": "纽约时间（America/New_York）",
    "Asia/Dubai": "迪拜时间（Asia/Dubai）",
    "UTC": "协调世界时（UTC）",
}


def alert_error(exc: Exception) -> None:
    st.error(str(exc))


def reset_editor(data: dict) -> None:
    st.session_state.chat = data
    st.session_state.editor_rev = st.session_state.get("editor_rev", 0) + 1


def reset_mail(data: dict) -> None:
    st.session_state.mail = data
    st.session_state.mail_rev = st.session_state.get("mail_rev", 0) + 1


if "chat" not in st.session_state:
    initial = new_conversation()
    assign_times(initial)
    st.session_state.chat = initial
    st.session_state.editor_rev = 0
if "batch" not in st.session_state:
    st.session_state.batch = []
if "mail" not in st.session_state:
    st.session_state.mail = new_mail_record()
    st.session_state.mail_rev = 0
if "nav_to" in st.session_state:
    st.session_state.page = st.session_state.pop("nav_to")

data = st.session_state.chat
revision = st.session_state.editor_rev
normalize_positions(data)


def fingerprint(chat: dict) -> str:
    return hashlib.sha256(json.dumps(chat, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def comma_list(value: str) -> list[str]:
    return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]


def upload_widget(label: str, key: str, assign, *, button_label: str = "保存并使用图片") -> None:
    uploaded = st.file_uploader(label, type=["png", "jpg", "jpeg", "webp"], key=f"{revision}-{key}")
    if uploaded and st.button(button_label, key=f"save-{revision}-{key}"):
        try:
            assign(store.save_image(uploaded.getvalue()))
            st.rerun()
        except Exception as exc:
            alert_error(exc)


def avatar_upload_widget(label: str, person_id: str, chat: dict) -> None:
    uploaded = st.file_uploader(label, type=["png", "jpg", "jpeg", "webp"],
                                key=f"{revision}-{person_id}-avatar")
    if uploaded:
        try:
            chat["participants"][person_id]["avatar_id"] = store.save_image(uploaded.getvalue())
            reset_editor(chat)
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
st.caption("人物、消息、邮件与 PI 均为模拟素材，仅供培训与演示；PI 导出带模拟标识。")
page = st.sidebar.radio("工作区", ["单组聊天与编辑", "PI 形式发票", "邮件记录截图", "批量生成", "历史与模板"], key="page")
st.sidebar.caption(f"本地数据：{store.root}")

if page == "单组聊天与编辑":
    left, right = st.columns([1.08, 1], gap="large")
    with left:
        st.subheader("场景与人物")
        data["title"] = st.text_input("标题", data["title"], key=f"{revision}-title")
        c1, c2 = st.columns(2)
        data["country"] = c1.text_input("国家", data["country"], key=f"{revision}-country")
        data["language"] = c2.text_input("聊天语言", data["language"], key=f"{revision}-language")
        zone_options = list(TIMEZONE_CHOICES) + ["自定义"]
        current_zone = data["timezone"]
        zone_choice = c1.selectbox("显示与排时所用时区", zone_options,
                                   index=zone_options.index(current_zone) if current_zone in TIMEZONE_CHOICES else len(zone_options) - 1,
                                   format_func=lambda value: TIMEZONE_CHOICES.get(value, "自定义 IANA 时区"),
                                   key=f"{revision}-zone-choice")
        if zone_choice == "自定义":
            entered_zone = c1.text_input("自定义 IANA 时区", current_zone, key=f"{revision}-zone-custom").strip()
            try:
                ZoneInfo(entered_zone)
                data["timezone"] = entered_zone
            except (KeyError, ValueError):
                c1.error("时区名称无效，请输入例如 Asia/Tokyo。")
        else:
            data["timezone"] = zone_choice
        st.caption("国家与时区可独立设置。更换时区会换算已有消息的显示钟点，不会静默改动其真实时间；新建对话默认北京时间。")
        data["tone"] = c2.text_input("语气", data["tone"], key=f"{revision}-tone")
        data["goal"] = st.text_input("对话目标", data["goal"], key=f"{revision}-goal")
        render_settings = data.setdefault("render_settings", {})
        current_style = render_settings.get("style", "classic")
        render_settings["style"] = st.selectbox("对话界面样式", ["classic", "wechat", "web"],
            index=["classic", "wechat", "web"].index(current_style),
            format_func=lambda value: {"classic": "WhatsApp 手机风格", "wechat": "微信风格", "web": "宽屏聊天风格"}[value],
            key=f"{revision}-render-style")
        group = data.setdefault("group", {"enabled": False, "name": "", "members": []})
        member_ids = {member["id"] for member in group.get("members", [])}
        group_messages = any(message.get("sender_id") in member_ids for message in data["messages"])
        group["enabled"] = st.checkbox("三人及以上群聊", bool(group.get("enabled")), key=f"{revision}-group-enabled",
            disabled=bool(group.get("enabled") and group_messages))
        if group_messages:
            st.caption("已有群成员消息。需要先调整这些消息的发送方，才能切回单聊。")
        if group["enabled"]:
            if not group["members"]:
                group["members"].append(new_group_member())
            group["name"] = st.text_input("群聊名称", group.get("name") or "商务讨论群", key=f"{revision}-group-name")
            st.caption("卖方消息显示在右侧；买方和其他成员显示在左侧。群成员姓名与头像只影响显示，不改变已有单聊记录。")
            for member in list(group["members"]):
                with st.expander(f"群成员 · {member['name']}"):
                    member["name"] = st.text_input("成员姓名", member["name"], key=f"{revision}-{member['id']}-name")
                    uploaded = st.file_uploader("成员头像", type=["png", "jpg", "jpeg", "webp"], key=f"{revision}-{member['id']}-avatar")
                    if uploaded:
                        member["avatar_id"] = store.save_image(uploaded.getvalue())
                    if member.get("avatar_id"):
                        st.image(str(store.image_path(member["avatar_id"])), width=64)
                    if st.button("移除成员", key=f"{revision}-{member['id']}-remove", disabled=len(group["members"]) <= 1 or any(m["sender_id"] == member["id"] for m in data["messages"])):
                        group["members"].remove(member)
                        reset_editor(data); st.rerun()
            if st.button("新增群成员", key=f"{revision}-add-group-member"):
                group["members"].append(new_group_member())
                reset_editor(data); st.rerun()
        if render_settings["style"] == "web":
            render_settings["tone"] = st.selectbox("宽屏色调", ["warm", "neutral"],
                index=["warm", "neutral"].index(render_settings.get("tone", "warm")),
                format_func=lambda value: {"warm": "柔和暖色", "neutral": "清爽中性"}[value],
                key=f"{revision}-render-tone")
        data["allow_details"] = st.checkbox("允许 AI 补充合理细节", data["allow_details"], key=f"{revision}-details")
        st.subheader("聊天头像")
        st.caption("选择 PNG、JPG 或 WebP 图片后立即应用。买方头像显示在 WhatsApp 风格聊天顶部；微信风格还会在买卖双方消息旁显示各自头像。")
        avatar_columns = st.columns(2)
        for column, person_id, heading in zip(avatar_columns, ("buyer", "seller"), ("买方", "卖方")):
            person = data["participants"][person_id]
            with column:
                st.markdown(f"**{heading}头像**")
                if person.get("avatar_id"):
                    try:
                        st.image(str(store.image_path(person["avatar_id"])), width=80)
                    except ValueError as exc:
                        alert_error(exc)
                    if st.button(f"移除{heading}头像", key=f"{revision}-{person_id}-remove-avatar"):
                        person["avatar_id"] = None
                        reset_editor(data)
                        st.rerun()
                else:
                    st.caption("尚未设置，预览时显示姓名首字母。")
                avatar_upload_widget(f"上传或更换{heading}头像", person_id, data)
        st.subheader("聊天顶部状态（模拟）")
        buyer = data["participants"]["buyer"]
        presence_options = ["hidden", "online", "last_seen"]
        current_presence = buyer.get("presence_mode", "hidden")
        buyer["presence_mode"] = st.selectbox(
            "买方状态", presence_options,
            index=presence_options.index(current_presence) if current_presence in presence_options else 0,
            format_func=lambda value: {"hidden": "不显示", "online": "在线", "last_seen": "最后上线时间"}[value],
            key=f"{revision}-buyer-presence",
        )
        if buyer["presence_mode"] == "last_seen":
            saved_last_seen = buyer.get("last_seen_at")
            initial_last_seen = (datetime.fromisoformat(saved_last_seen).astimezone(ZoneInfo(data["timezone"]))
                                 if saved_last_seen else datetime.now(ZoneInfo(data["timezone"])))
            presence_date, presence_time = st.columns(2)
            seen_date = presence_date.date_input("最后上线日期", initial_last_seen.date(),
                                                 key=f"{revision}-{data['timezone']}-last-seen-date")
            seen_time = presence_time.time_input("最后上线时间", initial_last_seen.time().replace(second=0, microsecond=0),
                                                 step=60, key=f"{revision}-{data['timezone']}-last-seen-time")
            try:
                buyer["last_seen_at"] = parse_manual(seen_date, seen_time, data["timezone"])
            except ValueError as exc:
                st.error(str(exc))
        st.caption("只用于 WhatsApp 风格预览与导出，不读取真实在线状态；“今天/昨天”相对于对话日期显示。")
        if render_settings["style"] in ("classic", "web"):
            st.caption("顶部即时预览（右侧完整聊天的顶部也会同步显示）")
            try:
                st.iframe(render_header_preview_html(data, store), height=68)
            except Exception as exc:
                alert_error(exc)
        else:
            st.info("当前选择的是微信风格；最后上线时间仅在 WhatsApp 风格中显示。")
        for person_id, heading in (("buyer", "买家"), ("seller", "卖家")):
            with st.expander(f"{heading}资料", expanded=False):
                person = data["participants"][person_id]
                person["name"] = st.text_input(f"{heading}姓名", person["name"], key=f"{revision}-{person_id}-name")
                person["role"] = st.text_input(f"{heading}职位", person["role"], key=f"{revision}-{person_id}-role")
                person["company"] = st.text_input(f"{heading}公司", person["company"], key=f"{revision}-{person_id}-company")
                person["region"] = st.text_input(f"{heading}国家/地区", person["region"], key=f"{revision}-{person_id}-region")
                person["style"] = st.text_input(f"{heading}表达风格", person["style"], key=f"{revision}-{person_id}-style")
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
        st.caption("关键词会在新生成的离线示例或 AI 草稿中使用；已编辑的消息不会被输入框自动改写。修改后请在下方点击“创建/重新生成整组”，或手动编辑消息。")
        upload_widget("上传产品图片（可逐张添加）", "product-image", lambda asset: product["image_ids"].append(asset))
        if product["image_ids"]:
            st.caption(f"已保存 {len(product['image_ids'])} 张产品图片，可在具体消息中插入。")
        st.subheader("PI 内容识别（形式发票）")
        st.caption("仅在本机提取可复制文字 PDF；提取值是待核对内容。原始 PDF 不保存到聊天记录。")
        pi_upload = st.file_uploader("上传 PI PDF", type=["pdf"], key=f"{revision}-pi-pdf")
        if pi_upload and st.button("提取 PI 文字", key=f"{revision}-pi-extract"):
            try:
                fields, raw_text, page_count = extract_pi(pi_upload.getvalue())
                st.session_state.pi_candidate = {"fields": fields, "raw_text": raw_text, "pages": page_count,
                                                 "digest": hashlib.sha256(pi_upload.getvalue()).hexdigest()[:16]}
                st.session_state.pi_candidate_id = data["conversation_id"]
            except Exception as exc:
                alert_error(exc)
        candidate = st.session_state.get("pi_candidate") if st.session_state.get("pi_candidate_id") == data["conversation_id"] else None
        if candidate:
            st.info(f"已提取 {candidate['pages']} 页。请逐项核对；空白字段可手动填写，错误字段请修改。")
            with st.expander("查看原始提取文字（用于核对）"):
                st.text_area("PDF 提取文字", candidate["raw_text"], height=220, disabled=True)
            reviewed = {}
            for field, label in FIELD_LABELS.items():
                reviewed[field] = st.text_input(label, candidate["fields"].get(field, ""), key=f"pi-review-{data['conversation_id']}-{candidate['digest']}-{field}")
            if st.button("确认以上 PI 字段用于模拟讨论"):
                data["pi"] = {"fields": {key: value.strip() for key, value in reviewed.items() if value.strip()}}
                st.success("PI 字段已确认。保存聊天时会保留这些字段，不保存原始 PDF。")
        if data.get("pi", {}).get("fields"):
            st.caption(f"当前聊天已确认 {len(data['pi']['fields'])} 项 PI 字段；可选择“PI 商务讨论”生成。")
            if data["language"] not in ("中文", "英语"):
                st.caption("PI 离线讨论目前提供中文和英语模板；当前语言将使用英语模板，生成后可逐条编辑。")
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
        mode = st.radio("生成方式", ["完全手动", "离线示例", "PI 商务讨论", "AI 生成"],
                        index=1, horizontal=True, key="generation_mode")
        create_label = "创建空白消息" if mode == "完全手动" else "创建/重新生成整组"
        if st.button(create_label, type="primary"):
            try:
                draft = copy.deepcopy(data)
                if mode == "AI 生成":
                    generate_ai(draft, int(count))
                elif mode == "PI 商务讨论":
                    pi_discussion(draft, int(count))
                elif mode == "离线示例":
                    offline_sample(draft, int(count))
                else:
                    people = list(sender_options(draft))
                    draft["messages"] = [new_message(people[i % len(people)]) for i in range(int(count))]
                    if rules["mode"] != "manual":
                        assign_times(draft)
                reset_editor(draft)
                st.rerun()
            except Exception as exc:
                alert_error(exc)
        st.caption("完全手动只创建空白消息；离线示例会填入演示文字。整组重新生成会替换当前消息，建议先保存当前版本。")
    try:
        display_zone = ZoneInfo(data["timezone"])
    except Exception:
        display_zone = ZoneInfo("UTC")
        st.error("时区无效，请选择预设时区或输入有效的 IANA 时区名称。")
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
    wide_preview_slot = st.empty() if data.get("render_settings", {}).get("style") == "web" else None
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
            people = sender_options(data)
            sender_ids = list(people)
            msg["sender_id"] = st.selectbox("发送方", sender_ids, index=sender_ids.index(msg["sender_id"]) if msg["sender_id"] in people else 0,
                format_func=lambda person_id: people[person_id].get("name") or person_id,
                key=key+"-sender", on_change=lambda m=msg, k=key+"-sender": m.update(sender_id=st.session_state[k]))
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
        filled_count = sum(bool(str(msg.get("text") or "").strip()) for msg in data["messages"])
        st.caption(f"当前 {len(data['messages'])} 条消息，其中 {filled_count} 条有文字。")
        if not filled_count:
            st.info("当前都是空白消息。请选择“离线示例”并点击“创建/重新生成整组”，或在下方消息编辑器手动填写。")
        if wide_preview_slot is None:
            preview(data)
        else:
            st.caption("宽屏完整预览显示在编辑区上方。")
    if wide_preview_slot is not None:
        with wide_preview_slot.container():
            st.subheader("宽屏完整预览")
            preview(data, height=800)
    with warnings_slot.container():
        try:
            for warning in keyword_warnings(data) + timeline_warnings(data):
                st.warning(warning)
        except Exception as exc:
            alert_error(exc)

elif page == "PI 形式发票":
    render_invoice_page(store, st.session_state.chat, st.session_state.mail, reset_editor, reset_mail)

elif page == "邮件记录截图":
    # The renderer has no persistent state. Reload it so Streamlit reruns do not
    # retain an imported renderer from before a live source update.
    render_mail_html = importlib.reload(mail_renderer).render_mail_html
    mail = st.session_state.mail
    mail_revision = st.session_state.mail_rev
    st.subheader("Gmail 风格模拟邮件记录")
    st.caption("编辑邮件主题、发件人、收件人、日期与正文，按 Gmail 风格预览并导出截图。")
    if st.button("新建示例邮件", key="mail-new"):
        reset_mail(new_mail_record())
        st.rerun()
    top1, top2 = st.columns([2, 1])
    mail["subject"] = top1.text_input("邮件主题", mail["subject"], key=f"mail-{mail_revision}-subject")
    mail["account"] = top2.text_input("邮箱账号（显示用）", mail["account"], key=f"mail-{mail_revision}-account")
    mail["folder"] = st.selectbox("截图所在文件夹", ["收件箱", "已发送"],
                                  index=["收件箱", "已发送"].index(mail["folder"]), key=f"mail-{mail_revision}-folder")
    st.markdown("#### 往来邮件")
    for index, message in enumerate(mail["messages"]):
        sender_label = message["sender"].split("<", 1)[0].strip() or "待填写发件人"
        with st.expander(f"邮件 {index + 1:02d} · {sender_label}", expanded=index == len(mail["messages"]) - 1):
            key = f"mail-{mail_revision}-{message['id']}"
            a, b = st.columns(2)
            message["sender"] = a.text_input("发件人", message["sender"], key=f"{key}-sender")
            message["recipient"] = b.text_input("收件人", message["recipient"], key=f"{key}-recipient")
            a, b = st.columns(2)
            message["cc"] = a.text_input("抄送（可选）", message["cc"], key=f"{key}-cc")
            message["sent_at"] = b.text_input("发送时间（YYYY-MM-DD HH:MM）", message["sent_at"], key=f"{key}-time")
            message["body"] = st.text_area("正文", message["body"], height=160, key=f"{key}-body")
            if st.button("删除此封邮件", key=f"{key}-delete", disabled=len(mail["messages"]) == 1):
                mail["messages"].pop(index)
                reset_mail(mail)
                st.rerun()
    if st.button("添加一封邮件", disabled=len(mail["messages"]) >= MAX_MAIL_MESSAGES):
        mail["messages"].append(new_mail_message(sender=f"<{mail['account']}>", recipient="<buyer@example.com>"))
        reset_mail(mail)
        st.rerun()
    st.subheader("实时预览")
    try:
        st.iframe(render_mail_html(mail), height=750)
    except Exception as exc:
        alert_error(exc)
    st.subheader("保存与导出")
    save1, save2, save3 = st.columns(3)
    if save1.button("保存邮件记录"):
        try:
            reset_mail(store.save_mail(mail))
            st.success("已保存到本地邮件记录。")
        except Exception as exc:
            alert_error(exc)
    if save2.button("另存新版本"):
        try:
            reset_mail(store.save_mail(mail, new_version=True))
            st.success("新版本已保存。")
        except Exception as exc:
            alert_error(exc)
    save3.download_button("下载邮件 JSON", json.dumps(mail, ensure_ascii=False, indent=2).encode("utf-8"),
                          file_name=f"mail_{mail['mail_id'][:8]}.json", mime="application/json")
    if st.button("准备邮件 PNG", type="primary"):
        try:
            validate_mail(mail)
            st.session_state.mail_png = screenshot_html(render_mail_html(mail), MAIL_WIDTH)
            st.session_state.mail_png_fingerprint = hashlib.sha256(render_mail_html(mail).encode("utf-8")).hexdigest()
        except Exception as exc:
            alert_error(exc)
    if st.session_state.get("mail_png") and st.session_state.get("mail_png_fingerprint") == hashlib.sha256(render_mail_html(mail).encode("utf-8")).hexdigest():
        st.download_button("下载邮件 PNG", st.session_state.mail_png,
                           file_name=safe_filename(mail["subject"], mail["mail_id"]), mime="image/png")
    st.subheader("已保存的邮件记录")
    for record in store.list_mail_records():
        rid = record["id"]
        cols = st.columns([4, 1, 1, 1])
        cols[0].write(f"{record['title']} · {record['updated_at']} · {rid[:8]}")
        if cols[1].button("载入", key=f"load-mail-{rid}"):
            try:
                reset_mail(store.load_mail(rid))
                st.rerun()
            except Exception as exc:
                alert_error(exc)
        if cols[2].button("删除", key=f"ask-delete-mail-{rid}"):
            st.session_state.mail_delete_target = rid
        if st.session_state.get("mail_delete_target") == rid:
            if cols[3].button("确认删除", key=f"confirm-delete-mail-{rid}"):
                try:
                    store.delete_mail(rid)
                    st.session_state.mail_delete_target = None
                    st.rerun()
                except Exception as exc:
                    alert_error(exc)

elif page == "批量生成":
    st.subheader("批量任务")
    st.caption("无密钥时批量创建可编辑的多语言离线示例。配置密钥后可逐组使用 AI 生成。")
    defaults = [{"国家": "法国", "语言": "法语", "时区": "Asia/Shanghai", "买家": "Camille Martin", "卖家": "Alex Chen", "买家身份": "采购经理", "卖家身份": "销售代表", "产品": "手机充电器", "必需词": "", "禁用词": "", "开始": "09:00", "结束": "16:30", "跨日天数": 0, "最小间隔": 5, "最大间隔": 30, "数量": 10},
                {"国家": "德国", "语言": "德语", "时区": "Asia/Shanghai", "买家": "Lena Weber", "卖家": "Alex Chen", "买家身份": "采购经理", "卖家身份": "销售代表", "产品": "手机充电器", "必需词": "", "禁用词": "", "开始": "09:00", "结束": "16:30", "跨日天数": 0, "最小间隔": 5, "最大间隔": 30, "数量": 10}]
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
