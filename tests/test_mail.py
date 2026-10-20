import io
from pathlib import Path

import pytest
from PIL import Image

from chatbench.exporter import screenshot_html
from chatbench.mail import MAIL_WIDTH, new_mail_record, render_mail_html, validate_mail
from chatbench.storage import Store


def test_mail_roundtrip_escaping_and_png(tmp_path):
    mail = new_mail_record()
    mail["subject"] = "询盘 <script>alert(1)</script>"
    mail["messages"][0]["body"] = "价格待确认 & 稍后答复"
    html = render_mail_html(mail)
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "价格待确认 &amp; 稍后答复" in html
    assert "模拟邮件记录 · DEMO" in html

    store = Store(tmp_path)
    saved = store.save_mail(mail)
    loaded = store.load_mail(saved["mail_id"])
    assert loaded["messages"][0]["body"] == mail["messages"][0]["body"]
    assert store.list_mail_records()[0]["id"] == mail["mail_id"]
    png = screenshot_html(render_mail_html(loaded), MAIL_WIDTH, scale=1)
    with Image.open(io.BytesIO(png)) as image:
        assert image.width == MAIL_WIDTH and image.height >= 690

    loaded["messages"][0]["sent_at"] = "invalid"
    with pytest.raises(ValueError, match="时间"):
        validate_mail(loaded)


def test_mail_editor_saves_edited_content(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    app.sidebar.radio[0].set_value("邮件记录截图").run()
    next(widget for widget in app.text_input if widget.label == "邮件主题").set_value("新主题").run()
    next(widget for widget in app.text_area if widget.label == "正文").set_value("已编辑的邮件正文").run()
    next(button for button in app.button if button.label == "保存邮件记录").click().run()
    assert not app.exception
    mail_id = app.session_state["mail"]["mail_id"]
    stored = Store(tmp_path / "data").load_mail(mail_id)
    assert stored["subject"] == "新主题"
    assert any(message["body"] == "已编辑的邮件正文" for message in stored["messages"])
