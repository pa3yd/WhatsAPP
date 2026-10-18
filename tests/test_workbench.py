import io
import json
import zipfile
from datetime import date, datetime, time
from pathlib import Path

import pytest
from PIL import Image

from chatbench.exporter import export_png, export_zip
from chatbench import generator
from chatbench.generator import clone_for_batch, offline_sample
from chatbench.models import keyword_warnings, new_conversation, validate_conversation
from chatbench.renderer import LABEL, render_html
from chatbench.storage import Store
from chatbench.time_engine import assign_times, parse_manual, timeline_warnings


def test_defaults_and_manual_time_preserved():
    chat = new_conversation()
    assert (chat["country"], chat["language"], chat["timezone"]) == ("法国", "法语", "Europe/Rome")
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
    assert LABEL in html and "data:image/png;base64," in html and "Photo de démonstration" in html
    assert len(store.save(loaded, new_version=True)["conversation_id"]) == 32


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


def test_ai_gate_and_single_message_preservation(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        generator._call_model("test", 1)
    chat = offline_sample(new_conversation(), 10)
    chat["messages"][4]["locked"] = True
    before = json.loads(json.dumps(chat, ensure_ascii=False))
    monkeypatch.setattr(generator, "_call_model", lambda prompt, count: [{"sender_id": "seller", "text": "Réponse modifiée"}])
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
