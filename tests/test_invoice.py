import io
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from chatbench.exporter import screenshot_html
from chatbench.invoice import (from_chat, from_explicit_text, from_mail, invoice_totals,
                               new_extra_term, new_invoice, new_item, to_chat_draft,
                               to_mail_draft, validate_invoice)
from chatbench.invoice_render import INVOICE_WIDTH, export_invoice_pdf, render_invoice_html
from chatbench.storage import Store


def sample_invoice():
    invoice = new_invoice()
    invoice["fields"].update(number="PI-DEMO-001", seller_name="模拟卖方", buyer_name="模拟买方",
                             seller_address="上海示例地址", buyer_address="巴黎示例地址",
                             currency="USD", incoterm="FOB Shanghai", payment_terms="30% 预付，70% 发货前",
                             delivery_terms="收到预付款后 30 天", freight="15", discount="5")
    invoice["items"][0].update(description="测试产品 A", model="A-1", quantity="10", unit_price="12.50")
    second = new_item()
    second.update(description="测试产品 B", quantity="2", unit="pcs", unit_price="20")
    invoice["items"].append(second)
    extra = new_extra_term()
    extra.update(label="检验", value="装运前人工核验")
    invoice["extra_terms"].append(extra)
    return invoice


def test_invoice_calculation_storage_and_editability(tmp_path):
    invoice = sample_invoice()
    amounts, subtotal, total = invoice_totals(invoice)
    assert amounts == [Decimal("125.00"), Decimal("40")]
    assert subtotal == Decimal("165.00") and total == Decimal("175.00")
    store = Store(tmp_path)
    saved = store.save_invoice(invoice)
    saved["items"].pop()
    saved["fields"]["payment_terms"] = "见最终确认单"
    updated = store.save_invoice(saved)
    assert len(store.load_invoice(updated["invoice_id"])["items"]) == 1
    assert store.load_invoice(updated["invoice_id"])["fields"]["payment_terms"] == "见最终确认单"
    version = store.save_invoice(updated, new_version=True)
    assert version["invoice_id"] != updated["invoice_id"]
    assert len(store.list_invoice_records()) == 2
    store.delete_invoice(version["invoice_id"])
    assert len(store.list_invoice_records()) == 1


def test_bidirectional_chat_mail_and_explicit_only():
    invoice = sample_invoice()
    assert to_chat_draft(invoice, style="wechat")["render_settings"]["style"] == "wechat"
    for converted, reverse in ((to_chat_draft(invoice), from_chat), (to_mail_draft(invoice), from_mail)):
        restored, count = reverse(converted)
        assert count >= 10
        assert restored["fields"]["number"] == "PI-DEMO-001"
        assert restored["fields"]["payment_terms"] == "30% 预付，70% 发货前"
        assert len(restored["items"]) == 2
        assert restored["items"][1]["description"] == "测试产品 B"
        assert restored["extra_terms"][0]["value"] == "装运前人工核验"
    guessed, count = from_explicit_text("我们谈过 10 件，每件可能 12 美元。", source_kind="聊天")
    assert count == 0 and not guessed["fields"]["number"]
    assert not guessed["items"][0]["quantity"]


def test_invoice_validation_and_exports():
    invoice = sample_invoice()
    html = render_invoice_html(invoice)
    assert "SIMULATED DRAFT" in html and "175.00" in html
    invoice["fields"]["notes"] = "<script>alert(1)</script>"
    html = render_invoice_html(invoice)
    assert "&lt;script&gt;" in html and "<script>" not in html
    pdf = export_invoice_pdf(invoice)
    assert pdf.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) >= 1
    assert "PROFORMA INVOICE" in reader.pages[0].extract_text()
    png = screenshot_html(html, INVOICE_WIDTH, scale=1)
    with Image.open(io.BytesIO(png)) as image:
        assert image.width == INVOICE_WIDTH and image.height >= 1123
    invoice["items"][0]["quantity"] = "invalid"
    with pytest.raises(ValueError, match="数量"):
        validate_invoice(invoice, complete=True)


def test_invoice_editor_saves_and_opens_chat_draft(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
    app.sidebar.radio[0].set_value("PI 形式发票").run()
    for label, value in (("PI 编号", "PI-UI-1"), ("卖方", "模拟供应商"), ("买方", "模拟客户"),
                         ("品名/描述", "测试品"), ("数量", "3"), ("单价", "8")):
        next(widget for widget in app.text_input if widget.label == label).set_value(value).run()
    next(button for button in app.button if button.label == "保存 PI 草稿").click().run()
    assert not app.exception
    invoice_id = app.session_state["invoice"]["invoice_id"]
    assert Store(tmp_path / "data").load_invoice(invoice_id)["fields"]["number"] == "PI-UI-1"
    next(button for button in app.button if button.label == "生成聊天和邮件草稿").click().run()
    next(button for button in app.button if button.label == "在聊天编辑器打开草稿").click().run()
    assert not app.exception
    assert app.session_state["page"] == "单组聊天与编辑"
    assert "PI-UI-1" in "\n".join(message["text"] for message in app.session_state["chat"]["messages"])
