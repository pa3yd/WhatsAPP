import io
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from chatbench.exporter import export_png
from chatbench.generator import regenerate_one
from chatbench.models import call_label, new_call_message, new_conversation, new_message, normalize_positions, validate_conversation
from chatbench.renderer import render_html
from chatbench.storage import Store


def test_call_roundtrip_render_and_export(tmp_path):
    store = Store(tmp_path)
    chat = new_conversation()
    chat["render_settings"].update(style="wechat", wechat_date_format="full")
    chat["conversation_date"] = "2026-10-14"
    call = new_call_message(timestamp="2026-10-14T14:17:00+08:00", duration_seconds=1251)
    chat["messages"] = [new_message("buyer", "可以", timestamp="2026-10-14T13:55:00+08:00"), call]
    normalize_positions(chat)
    loaded = store.load(store.save(chat)["conversation_id"])
    assert loaded["messages"][1]["type"] == "call"
    assert loaded["messages"][1]["call_duration_seconds"] == 1251
    assert loaded["messages"][1]["timestamp"] == call["timestamp"]
    html = render_html(loaded, store)
    assert "10月14日 星期三 14:17" in html
    assert "通话时长 20:51" in html and 'class="call-icon"' in html
    # A call is still visible when imported JSON has no redundant display text.
    loaded["messages"][1]["text"] = ""
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 720, "height": 800})
            for sender in ("seller", "buyer"):
                loaded["messages"][1]["sender_id"] = sender
                page.set_content(render_html(loaded, store))
                content = page.locator(".call-content")
                assert content.inner_text() == "通话时长 20:51"
                label = content.locator("span").bounding_box()
                icon = content.locator("svg").bounding_box()
                assert label and icon
                assert (icon["x"] > label["x"]) == (sender == "seller")
                assert content.locator("svg").is_visible()
        finally:
            browser.close()
    with Image.open(io.BytesIO(export_png(loaded, store, scale=1))) as png:
        assert png.width == 720


def test_call_duration_validation_and_manual_editing():
    chat = new_conversation()
    call = new_call_message(timestamp="2026-10-14T14:17:00+08:00", duration_seconds=3661)
    chat["messages"] = [call]
    assert call_label(call) == "通话时长 1:01:01"
    validate_conversation(chat)
    with pytest.raises(ValueError, match="通话记录请手动编辑"):
        regenerate_one(chat, call["id"])
    for invalid in (-1, 360000, True, "20:51"):
        call["call_duration_seconds"] = invalid
        with pytest.raises(ValueError, match="通话时长"):
            validate_conversation(chat)


def test_call_editor_inserts_and_updates_duration(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
    next(widget for widget in app.selectbox if widget.label == "对话界面样式").set_value("wechat").run()
    original_ids = [message["id"] for message in app.session_state["chat"]["messages"]]
    next(button for button in app.button if button.label == "插入通话记录").click().run()
    assert not app.exception
    chat = app.session_state["chat"]
    assert [message["id"] for message in chat["messages"][:-1]] == original_ids
    assert chat["messages"][-1]["type"] == "call"
    assert chat["messages"][-1]["call_duration_seconds"] == 1251
    original_time = chat["messages"][-1]["timestamp"]
    next(widget for widget in app.number_input if widget.label == "时长：分钟").set_value(12).run()
    next(button for button in app.button if button.label == "保存聊天").click().run()
    assert not app.exception
    chat = app.session_state["chat"]
    loaded = Store(tmp_path / "data").load(chat["conversation_id"])
    assert loaded["messages"][-1]["type"] == "call"
    assert loaded["messages"][-1]["call_duration_seconds"] == 771
    assert loaded["messages"][-1]["text"] == "通话时长 12:51"
    assert loaded["messages"][-1]["timestamp"] == original_time
