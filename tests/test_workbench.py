import io
import json
import zipfile
from datetime import date, datetime, time
from pathlib import Path
from xml.etree import ElementTree

import pytest
from PIL import Image
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from chatbench.exporter import export_png, export_zip
from chatbench import generator
from chatbench.generator import clone_for_batch, offline_sample, pi_discussion
from chatbench.models import keyword_warnings, new_conversation, new_group_member, validate_conversation
from chatbench.pi_reader import extract_pi
from chatbench.renderer import render_header_preview_html, render_html, render_width
from chatbench.storage import Store
from chatbench.time_engine import assign_times, parse_manual, timeline_warnings
from chatbench.wallpaper import WALLPAPER_DATA_URI, _wallpaper_svg


def test_defaults_and_manual_time_preserved():
    chat = new_conversation()
    assert (chat["country"], chat["language"], chat["timezone"]) == ("法国", "法语", "Asia/Shanghai")
    assign_times(chat)
    before = chat["messages"][5]["timestamp"]
    custom = parse_manual(date.fromisoformat(chat["conversation_date"]), time(11, 17), chat["timezone"])
    chat["messages"][5].update(timestamp=custom, manual_time=True)
    assign_times(chat)
    assert chat["messages"][5]["timestamp"] == custom
    assert before != custom


def test_conflicting_anchors_are_atomic():
    chat = new_conversation()
    assign_times(chat)
    old = [m["timestamp"] for m in chat["messages"]]
    impossible = parse_manual(date.fromisoformat(chat["conversation_date"]), time(16, 25), chat["timezone"])
    chat["messages"][2].update(timestamp=impossible, manual_time=True)
    with pytest.raises(ValueError, match="固定|间隔"):
        assign_times(chat)
    assert [m["timestamp"] for m in chat["messages"]][3:] == old[3:]


def test_order_is_not_silently_retimed():
    chat = new_conversation()
    assign_times(chat)
    chat["messages"][0], chat["messages"][1] = chat["messages"][1], chat["messages"][0]
    assert any("早于上一条" in warning for warning in timeline_warnings(chat))


def test_type_interval_and_cross_day():
    chat = new_conversation()
    chat["time_rules"].update(start="23:00", end="01:00", end_day_offset=1, min_minutes=5, max_minutes=30,
                              type_intervals={"image_text": {"min_minutes": 40, "max_minutes": 60}})
    chat["messages"][3]["type"] = "image_text"
    chat["messages"][3]["asset_id"] = "a" * 32
    assign_times(chat)
    moments = [datetime.fromisoformat(m["timestamp"]) for m in chat["messages"]]
    assert (moments[3] - moments[2]).total_seconds() / 60 >= 40
    assert moments[-1].date() > moments[0].date()


def test_keywords_and_corrupt_file(tmp_path):
    chat = new_conversation()
    chat["keywords"] = {"required": ["USB-C"], "forbidden": ["保证"]}
    assert "缺少必需关键词：USB-C" in keyword_warnings(chat)
    store = Store(tmp_path)
    (store.chats / f"{chat['conversation_id']}.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError, match="无法读取"):
        store.load(chat["conversation_id"])


def test_image_roundtrip_and_render(tmp_path):
    store = Store(tmp_path)
    img = Image.new("RGB", (80, 50), "orange")
    stream = io.BytesIO(); img.save(stream, format="PNG")
    asset = store.save_image(stream.getvalue())
    chat = new_conversation(); assign_times(chat)
    chat["product"]["image_ids"].append(asset)
    chat["messages"][3].update(asset_id=asset, type="image_text", text="Photo de démonstration")
    saved = store.save(chat)
    loaded = store.load(saved["conversation_id"])
    assert loaded["messages"][3]["asset_id"] == asset
    html = render_html(loaded, store)
    assert "data:image/png;base64," in html and "Photo de démonstration" in html
    assert "虚构人物与场景" not in html and "SIMULATED CHAT" not in html
    assert '<div class="sub">' not in html
    assert ".classic .sender{display:none}" in html
    assert len(store.save(loaded, new_version=True)["conversation_id"]) == 32


def test_whatsapp_last_seen_roundtrip_and_wallpaper(tmp_path):
    store = Store(tmp_path)
    chat = new_conversation()
    chat["render_settings"]["style"] = "web"
    chat["conversation_date"] = "2026-10-20"
    chat["participants"]["buyer"].update(presence_mode="last_seen", last_seen_at="2026-10-20T15:09:00+08:00")
    loaded = store.load(store.save(chat)["conversation_id"])
    html = render_html(loaded, store)
    assert "最后上线时间：今天 15:09" in html
    assert "最后上线时间：今天 15:09" in render_header_preview_html(loaded, store)
    assert "data:image/svg+xml;base64," in html
    assert 'font-family:"Segoe UI","Helvetica Neue"' in html
    assert "最后上线时间：今天 15:09" in render_html({**loaded, "render_settings": {"style": "classic"}}, store)
    assert "最后上线时间：今天 15:09" not in render_html({**loaded, "render_settings": {"style": "wechat"}}, store)
    assert export_png(loaded, store, scale=1).startswith(b"\x89PNG")
    loaded["render_settings"] = {"style": "classic", "tone": "neutral"}
    neutral_html = render_html(loaded, store)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 420, "height": 720})
            page.set_content(neutral_html)
            assert page.locator(".head-main small").inner_text() == "最后上线时间：今天 15:09"
            assert "data:image/svg+xml" in page.locator(".chat").evaluate("el => getComputedStyle(el).backgroundImage")
        finally:
            browser.close()

    loaded["participants"]["buyer"]["last_seen_at"] = "2026-10-19T23:09:00+08:00"
    assert "最后上线时间：昨天 23:09" in render_html(loaded, store)
    loaded["timezone"] = "Europe/Paris"
    assert "最后上线时间：昨天 17:09" in render_html(loaded, store)
    loaded["timezone"] = "Asia/Shanghai"
    loaded["participants"]["buyer"]["presence_mode"] = "online"
    assert "<small>在线</small>" in render_html(loaded, store)
    loaded["participants"]["buyer"]["presence_mode"] = "hidden"
    assert "<small>在线</small>" not in render_html(loaded, store)

    legacy = new_conversation()
    legacy["participants"]["buyer"].pop("presence_mode")
    legacy["participants"]["buyer"].pop("last_seen_at")
    validate_conversation(legacy)
    assert "最后上线时间" not in render_html(legacy, store)
    legacy["participants"]["buyer"]["presence_mode"] = "last_seen"
    with pytest.raises(ValueError, match="最后上线时间"):
        validate_conversation(legacy)


def test_wallpaper_is_dense_deterministic_and_embedded(tmp_path):
    svg = _wallpaper_svg()
    ElementTree.fromstring(svg)
    assert svg == _wallpaper_svg()
    assert svg.count("<use ") >= 120
    assert WALLPAPER_DATA_URI.startswith("data:image/svg+xml;base64,")
    store = Store(tmp_path)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            for style in ("classic", "web"):
                for tone in ("warm", "neutral"):
                    chat = new_conversation()
                    chat["render_settings"].update(style=style, tone=tone)
                    page.set_content(render_html(chat, store))
                    background = page.locator(".chat").evaluate("el => getComputedStyle(el).backgroundImage")
                    assert "data:image/svg+xml" in background
        finally:
            browser.close()


def test_last_seen_editor_controls(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    next(box for box in app.selectbox if box.label == "买方状态").set_value("last_seen").run()
    assert not app.exception
    assert any(widget.label == "最后上线日期" for widget in app.date_input)
    next(widget for widget in app.date_input if widget.label == "最后上线日期").set_value(date(2026, 10, 20)).run()
    next(widget for widget in app.time_input if widget.label == "最后上线时间").set_value(time(15, 9)).run()
    assert not app.exception
    assert app.session_state["chat"]["participants"]["buyer"]["last_seen_at"] == "2026-10-20T15:09+08:00"


def test_english_offline_business_sample_uses_current_product():
    chat = new_conversation()
    chat["language"] = "英语"
    chat["product"]["name"] = "solar chargers"
    offline_sample(chat, 10)
    assert "solar chargers" in chat["messages"][0]["text"]
    assert "MOQ" in chat["messages"][5]["text"]
    assert "PI terms" in chat["messages"][9]["text"]
    chat["product"]["name"] = "手机充电器"
    offline_sample(chat, 2)
    assert "this product" in chat["messages"][0]["text"]
    assert "手机充电器" not in chat["messages"][0]["text"]


def test_offline_keywords_are_questions_not_confirmed_quotes():
    chat = new_conversation()
    chat["language"] = "英语"
    chat["keywords"]["required"] = ["$2.5/pcs", "1000pcs"]
    offline_sample(chat, 10)
    buyer_text = chat["messages"][4]["text"]
    assert "$2.5/pcs" in buyer_text and "1000pcs" in buyer_text
    assert chat["messages"][4]["sender_id"] == "buyer"
    assert "confirm" in buyer_text.lower()
    assert "confirmed answer" in chat["messages"][5]["text"]
    original = [message["text"] for message in chat["messages"]]
    chat["keywords"]["forbidden"] = ["1000pcs"]
    with pytest.raises(ValueError, match="冲突"):
        offline_sample(chat, 10)
    assert [message["text"] for message in chat["messages"]] == original
    chat["keywords"]["forbidden"] = []
    offline_sample(chat, 3)
    assert all(word in chat["messages"][0]["text"] for word in chat["keywords"]["required"])


def test_wechat_style_roundtrip_and_export(tmp_path):
    store = Store(tmp_path)
    chat = offline_sample(new_conversation(), 4)
    chat["render_settings"]["style"] = "wechat"
    loaded = store.load(store.save(chat)["conversation_id"])
    html = render_html(loaded, store)
    assert 'body class="wechat warm"' in html
    assert 'class="message-avatar placeholder"' in html
    assert "虚构人物与场景" not in html and "SIMULATED CHAT" not in html
    png = export_png(loaded, store)
    assert png.startswith(b"\x89PNG")
    assert 'body class="classic warm"' in render_html(new_conversation(), store)


def test_classic_mobile_chat_renders_emoji_and_message_status(tmp_path):
    store = Store(tmp_path)
    chat = offline_sample(new_conversation(), 2)
    chat["messages"][1]["text"] = "好的 🙂"
    html = render_html(chat, store)
    assert 'class="status-bar"' in html
    assert 'class="home-indicator"' in html
    assert "好的 🙂" in html
    assert html.count('class="read-mark"') == 1
    assert export_png(chat, store, scale=1).startswith(b"\x89PNG")


def test_three_person_group_roundtrip_and_both_chat_styles(tmp_path):
    store = Store(tmp_path)
    chat = new_conversation()
    member = new_group_member("Nina")
    chat["group"] = {"enabled": True, "name": "采购讨论群", "members": [member]}
    offline_sample(chat, 6)
    assert {message["sender_id"] for message in chat["messages"]} == {"buyer", "seller", member["id"]}
    saved = store.load(store.save(chat)["conversation_id"])
    for style in ("classic", "wechat"):
        saved["render_settings"]["style"] = style
        html = render_html(saved, store)
        assert "采购讨论群" in html and "Nina" in html
        assert "group" in html and 'class="message-avatar placeholder"' in html
        assert export_png(saved, store, scale=1).startswith(b"\x89PNG")
    saved["group"]["members"] = []
    with pytest.raises(ValueError, match="至少需要三名成员"):
        validate_conversation(saved)


def test_group_ai_uses_member_ids_without_live_api(monkeypatch):
    chat = new_conversation()
    member = new_group_member("Nina")
    chat["group"] = {"enabled": True, "name": "采购讨论群", "members": [member]}
    def fake_model(prompt, count, sender_ids=None):
        assert sender_ids == ["buyer", "seller", member["id"]]
        return [{"sender_id": sender_ids[i % len(sender_ids)], "text": f"消息 {i}"} for i in range(count)]
    monkeypatch.setattr(generator, "_call_model", fake_model)
    generator.generate_ai(chat, 6)
    assert {message["sender_id"] for message in chat["messages"]} == {"buyer", "seller", member["id"]}
    validate_conversation(chat)


def test_group_editor_adds_member_and_sender_choice(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    next(box for box in app.checkbox if box.label == "三人及以上群聊").set_value(True).run()
    assert not app.exception
    member_id = app.session_state["chat"]["group"]["members"][0]["id"]
    sender = next(box for box in app.selectbox if box.label == "发送方")
    sender.set_value(member_id).run()
    assert not app.exception
    assert app.session_state["chat"]["messages"][0]["sender_id"] == member_id


def test_wechat_skips_empty_messages_and_aligns_replies_right(tmp_path):
    store = Store(tmp_path)
    blank = new_conversation()
    blank["render_settings"]["style"] = "wechat"
    assert 'class="row ' not in render_html(blank, store)

    chat = offline_sample(blank, 4)
    chat["messages"][1]["text"] = "  好的  "
    html = render_html(chat, store)
    assert ">好的</div>" in html
    assert ">  好的  </div>" not in html
    assert render_width(chat) == 720
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 720, "height": 800})
            page.set_content(html)
            incoming = page.locator(".row.in .bubble").first.bounding_box()
            outgoing = page.locator(".row.out .bubble").first.bounding_box()
            outgoing_avatar = page.locator(".row.out .message-avatar").first.bounding_box()
            assert incoming and outgoing and outgoing_avatar
            assert outgoing["x"] > incoming["x"] + 50
            assert outgoing_avatar["x"] >= outgoing["x"] + outgoing["width"]
            assert outgoing["width"] < 80
            assert page.locator(".row.out .bubble").first.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(157, 242, 159)"
            assert page.locator(".chat").evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(250, 250, 250)"
        finally:
            browser.close()


def test_wechat_wrapped_message_uses_bubble_width(tmp_path):
    store = Store(tmp_path)
    chat = new_conversation()
    chat["language"] = "英语"
    chat["render_settings"]["style"] = "wechat"
    offline_sample(chat, 4)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 720, "height": 800})
            page.set_content(render_html(chat, store))
            first_line_gap = page.locator(".row.out .bubble").first.evaluate("""bubble => {
                const content = bubble.querySelector('.text');
                const range = document.createRange();
                range.selectNodeContents(content);
                return bubble.getBoundingClientRect().right - range.getClientRects()[0].right;
            }""")
            assert first_line_gap < 60
        finally:
            browser.close()


def test_wide_chat_tones_export_and_keep_simulated_label(tmp_path):
    store = Store(tmp_path)
    chat = offline_sample(new_conversation(), 4)
    chat["render_settings"]["style"] = "web"
    for tone in ("warm", "neutral"):
        chat["render_settings"]["tone"] = tone
        html = render_html(chat, store)
        assert f'body class="web {tone}"' in html
        assert "SIMULATED CHAT" not in html and 'class="composer"' in html
        png = export_png(chat, store, scale=1)
        with Image.open(io.BytesIO(png)) as image:
            assert image.width == 1000


def test_pi_text_pdf_review_and_offline_discussion(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 700 Td (PI No: PI-123) Tj 0 -20 Td (Grand Total: USD 1200) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO(); writer.write(buffer)
    fields, raw_text, pages = extract_pi(buffer.getvalue())
    assert pages == 1 and fields["number"] == "PI-123" and fields["total"] == "USD 1200"
    chat = new_conversation(); chat["language"] = "中文"
    chat["pi"] = {"fields": {"number": fields["number"], "total": fields["total"]}}
    pi_discussion(chat, 6)
    assert "USD 1200" in chat["messages"][2]["text"]
    assert "PI-123" in chat["messages"][4]["text"]
    loaded = Store(tmp_path).load(Store(tmp_path).save(chat)["conversation_id"])
    assert loaded["pi"] == chat["pi"] and "raw_text" not in loaded["pi"]
    assert raw_text.startswith("PI No")


def test_pi_scanned_pdf_requires_text():
    writer = PdfWriter(); writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO(); writer.write(buffer)
    with pytest.raises(ValueError, match="没有可复制文字"):
        extract_pi(buffer.getvalue())


def test_batch_failure_does_not_erase_success(tmp_path):
    base = new_conversation()
    good = clone_for_batch(base, country="德国", language="德语", timezone="Europe/Berlin", buyer="Lena", seller="Alex", count=10)
    assert validate_conversation(good)["messages"][0]["text"].startswith("Guten")
    with pytest.raises(Exception):
        clone_for_batch(base, country="坏", language="中文", timezone="Bad/Zone", buyer="A", seller="B", count=10)
    assert len(good["messages"]) == 10


def test_png_and_zip_full_content(tmp_path):
    store = Store(tmp_path)
    chat = offline_sample(new_conversation(), 10)
    photo = Image.new("RGB", (120, 70), (249, 119, 25))
    buffer = io.BytesIO(); photo.save(buffer, format="PNG")
    asset_id = store.save_image(buffer.getvalue())
    chat["product"]["image_ids"].append(asset_id)
    chat["participants"]["buyer"]["avatar_id"] = asset_id
    chat["messages"][5].update(asset_id=asset_id, type="image_text")
    png = export_png(chat, store)
    with Image.open(io.BytesIO(png)) as image:
        assert image.width >= 1000 and image.height > 1000
        assert bytes((249, 119, 25)) in image.convert("RGB").tobytes()
    archive, errors = export_zip([{"data": chat}], store)
    assert not errors
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert len(z.namelist()) == 1
        assert z.read(z.namelist()[0]).startswith(b"\x89PNG")


def test_buyer_avatar_in_whatsapp_header_and_wechat_messages(tmp_path):
    store = Store(tmp_path)
    photo = Image.new("RGB", (64, 64), "blue")
    buffer = io.BytesIO()
    photo.save(buffer, format="PNG")
    chat = offline_sample(new_conversation(), 2)
    chat["participants"]["buyer"]["avatar_id"] = store.save_image(buffer.getvalue())
    html = render_html(chat, store)
    assert '<img class="avatar" src="data:image/png;base64,' in html
    saved = store.save(chat)
    assert store.load(saved["conversation_id"])["participants"]["buyer"]["avatar_id"] == chat["participants"]["buyer"]["avatar_id"]
    chat["render_settings"]["style"] = "wechat"
    html = render_html(chat, store)
    assert '<img class="message-avatar" src="data:image/png;base64,' in html


def test_avatar_upload_entry_and_remove(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    upload_labels = [widget.label for widget in app.get("file_uploader")]
    assert "上传或更换买方头像" in upload_labels
    assert "上传或更换卖方头像" in upload_labels
    assert not any(button.label.startswith("应用买方头像") for button in app.button)
    photo = Image.new("RGB", (32, 32), "green")
    buffer = io.BytesIO()
    photo.save(buffer, format="PNG")
    app.session_state["chat"]["participants"]["buyer"]["avatar_id"] = Store(tmp_path / "data").save_image(buffer.getvalue())
    app.run()
    next(button for button in app.button if button.label == "移除买方头像").click().run()
    assert not app.exception
    assert app.session_state["chat"]["participants"]["buyer"]["avatar_id"] is None


def test_streamlit_save_and_fresh_session_load(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    first = AppTest.from_file(str(app_path), default_timeout=30).run()
    first.text_area[1].set_value("Bonjour, essai sauvegardé").run()
    next(button for button in first.button if button.label == "保存聊天").click().run()
    assert not first.exception
    record_id = first.session_state["chat"]["conversation_id"]
    assert (tmp_path / "data" / "chats" / f"{record_id}.json").exists()

    fresh = AppTest.from_file(str(app_path), default_timeout=30).run()
    fresh.sidebar.radio[0].set_value("历史与模板").run()
    next(button for button in fresh.button if button.label == "载入").click().run()
    assert not fresh.exception
    assert fresh.session_state["chat"]["messages"][0]["text"] == "Bonjour, essai sauvegardé"


def test_timezone_choices_default_beijing_and_preserve_existing_instants(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    assert app.session_state["chat"]["timezone"] == "Asia/Shanghai"
    original_stamp = app.session_state["chat"]["messages"][0]["timestamp"]
    timezone_choice = next(box for box in app.selectbox if box.label == "显示与排时所用时区")
    timezone_choice.set_value("Europe/Paris").run()
    assert not app.exception
    assert app.session_state["chat"]["timezone"] == "Europe/Paris"
    assert app.session_state["chat"]["messages"][0]["timestamp"] == original_stamp
    timezone_choice = next(box for box in app.selectbox if box.label == "显示与排时所用时区")
    timezone_choice.set_value("自定义").run()
    next(box for box in app.text_input if box.label == "自定义 IANA 时区").set_value("Asia/Tokyo").run()
    assert app.session_state["chat"]["timezone"] == "Asia/Tokyo"
    next(box for box in app.text_input if box.label == "自定义 IANA 时区").set_value("Invalid/Zone").run()
    assert app.session_state["chat"]["timezone"] == "Asia/Tokyo"
    assert not app.exception


def test_generation_mode_stays_selected_and_populates_preview(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    mode = next(radio for radio in app.radio if radio.label == "生成方式")
    assert mode.value == "离线示例"
    next(button for button in app.button if button.label == "创建/重新生成整组").click().run()
    assert not app.exception
    assert app.session_state["generation_mode"] == "离线示例"
    assert all(message["text"] for message in app.session_state["chat"]["messages"])


def test_ai_gate_and_single_message_preservation(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        generator._call_model("test", 1)
    chat = offline_sample(new_conversation(), 10)
    chat["messages"][4]["locked"] = True
    before = json.loads(json.dumps(chat, ensure_ascii=False))
    monkeypatch.setattr(generator, "_call_model", lambda prompt, count, sender_ids=None: [{"sender_id": "seller", "text": "Réponse modifiée"}])
    generator.regenerate_one(chat, chat["messages"][5]["id"])
    assert chat["messages"][5]["text"] == "Réponse modifiée"
    assert chat["messages"][5]["timestamp"] == before["messages"][5]["timestamp"]
    assert chat["messages"][5]["asset_id"] == before["messages"][5]["asset_id"]
    assert chat["messages"][4] == before["messages"][4]
    with pytest.raises(ValueError, match="锁定"):
        generator.regenerate_one(chat, chat["messages"][4]["id"])


def test_batch_ui_retains_success_when_one_group_fails(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    original = generator.clone_for_batch

    def fail_germany(source, **kwargs):
        if kwargs["country"] == "德国":
            raise ValueError("测试用单组失败")
        return original(source, **kwargs)

    monkeypatch.setattr(generator, "clone_for_batch", fail_germany)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    app.sidebar.radio[0].set_value("批量生成").run()
    next(button for button in app.button if button.label == "运行批量任务").click().run()
    assert not app.exception
    assert [item["status"] for item in app.session_state["batch"]] == ["成功", "失败"]
    assert "测试用单组失败" in app.session_state["batch"][1]["error"]
    assert len(app.session_state["batch"][0]["data"]["messages"]) == 10
