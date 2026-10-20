from __future__ import annotations

import io
from decimal import Decimal
from html import escape as html_escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .invoice import invoice_totals, money, validate_invoice

INVOICE_WIDTH = 794


def render_invoice_html(invoice: dict) -> str:
    validate_invoice(invoice)
    fields = invoice["fields"]

    def h(value: str) -> str:
        return html_escape(value or "")

    def field(label: str, value: str) -> str:
        return f'<div class="field"><span>{h(label)}</span><strong>{h(value) if value.strip() else "待填写"}</strong></div>'

    try:
        amounts, subtotal, total = invoice_totals(invoice)
    except ValueError:
        amounts = []
        subtotal = total = None
    rows = []
    for index, item in enumerate(invoice["items"], 1):
        amount = money(amounts[index - 1]) if amounts else "待确认"
        description = h(item["description"]) or "待填写品名"
        model = f'<small>{h(item["model"])}</small>' if item["model"].strip() else ""
        rows.append(f'<tr><td>{index}</td><td>{description}{model}</td><td>{h(item["quantity"])}</td><td>{h(item["unit"])}</td><td>{h(item["unit_price"])}</td><td>{amount}</td></tr>')
    extras = "".join(field(term["label"], term["value"]) for term in invoice["extra_terms"] if term["label"].strip() or term["value"].strip())
    total_text = f'{h(fields["currency"])} {money(total)}' if total is not None else "待确认"
    optional_costs = "".join(field(label, fields[key]) for key, label in (("freight", "运费"), ("insurance", "保险费"), ("discount", "折扣")) if fields[key].strip() and fields[key].strip() not in ("0", "0.00"))
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{{box-sizing:border-box}}html,body{{margin:0;background:#e7ebed;color:#263336;font-family:Arial,"Microsoft YaHei",sans-serif}}
.frame{{width:{INVOICE_WIDTH}px;max-width:100%;min-height:1123px;margin:auto;padding:42px 48px;background:#fff;box-shadow:0 5px 22px #24333620}}
.draft{{display:inline-block;color:#8e6036;background:#fff2df;border:1px solid #f0d9b2;border-radius:5px;padding:5px 9px;font-size:11px;font-weight:700;letter-spacing:.05em}}
.top{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #2b736c;padding:19px 0 22px}}
h1{{font-size:27px;line-height:1.15;margin:0;color:#1f4f4b;letter-spacing:.03em}}.subtitle{{font-size:14px;color:#687b78;margin-top:5px}}
.meta{{text-align:right;font-size:12px;line-height:1.85}}.meta strong{{color:#233a39}}
.parties{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:27px 0}}
.card{{border:1px solid #dfe8e5;border-radius:8px;padding:16px;min-height:130px;overflow-wrap:anywhere}}
.card h2{{font-size:11px;letter-spacing:.1em;color:#36736d;margin:0 0 11px}}.card strong{{display:block;font-size:15px;margin-bottom:7px}}
.card p{{margin:4px 0;color:#5c6d6b;font-size:12px;line-height:1.5;white-space:pre-wrap}}
h3{{font-size:12px;color:#356d67;letter-spacing:.08em;margin:24px 0 9px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}th{{text-align:left;background:#e9f2ef;color:#355c58;font-weight:700;padding:9px 7px}}
td{{padding:10px 7px;border-bottom:1px solid #e5ebe9;vertical-align:top;overflow-wrap:anywhere}}
td small{{display:block;color:#87918e;margin-top:5px}}td:nth-child(3),td:nth-child(5),td:nth-child(6){{text-align:right}}
.totals{{width:270px;margin:17px 0 0 auto;font-size:12px}}.total-line{{display:flex;justify-content:space-between;padding:6px 0}}
.grand{{font-weight:700;font-size:17px;color:#205a54;border-top:2px solid #afccc5;margin-top:5px;padding-top:11px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;column-gap:24px}}.field{{font-size:12px;padding:9px 0;border-bottom:1px solid #edf0ef;display:flex;gap:8px;justify-content:space-between;overflow-wrap:anywhere}}
.field span{{color:#72807d;flex:0 0 105px}}.field strong{{font-weight:500;flex:1;text-align:right;white-space:pre-wrap}}
.notes{{font-size:12px;color:#3d4e4b;white-space:pre-wrap;line-height:1.6;margin-top:8px}}
.footer{{border-top:1px solid #dce6e2;margin-top:35px;padding-top:12px;font-size:11px;color:#8a9692;text-align:right}}
@media(max-width:700px){{.frame{{padding:25px 20px;min-height:0}}.parties,.grid{{grid-template-columns:1fr}}.meta{{text-align:left}}.top{{display:block}}.top .meta{{margin-top:15px}}}}
</style></head><body><div class="frame"><span class="draft">SIMULATED DRAFT · 模拟草稿</span>
<header class="top"><div><h1>PROFORMA INVOICE</h1><div class="subtitle">形式发票 · 请在正式使用前逐项核对</div></div>
<div class="meta"><div>PI NO.　<strong>{h(fields['number']) or '待填写'}</strong></div><div>DATE　<strong>{h(fields['issue_date']) or '待填写'}</strong></div><div>VALID UNTIL　<strong>{h(fields['valid_until']) or '—'}</strong></div></div></header>
<section class="parties"><div class="card"><h2>SELLER / 卖方</h2><strong>{h(fields['seller_name']) or '待填写'}</strong><p>{h(fields['seller_address'])}</p><p>{h(fields['seller_contact'])}　{h(fields['seller_phone'])}</p><p>{h(fields['seller_email'])}</p><p>{h(fields['seller_tax_id'])}</p></div>
<div class="card"><h2>BUYER / 买方</h2><strong>{h(fields['buyer_name']) or '待填写'}</strong><p>{h(fields['buyer_address'])}</p><p>{h(fields['buyer_contact'])}　{h(fields['buyer_phone'])}</p><p>{h(fields['buyer_email'])}</p><p>{h(fields['buyer_tax_id'])}</p></div></section>
<h3>GOODS / 商品明细</h3><table><thead><tr><th>#</th><th>品名 / 规格</th><th>数量</th><th>单位</th><th>单价</th><th>金额</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<div class="totals"><div class="total-line"><span>小计</span><span>{money(subtotal) if subtotal is not None else '待确认'}</span></div>{optional_costs}
<div class="total-line grand"><span>总金额</span><span>{total_text}</span></div></div>
<h3>TERMS / 商务与运输条款</h3><section class="grid">
{field('币种', fields['currency'])}{field('贸易条款', fields['incoterm'])}{field('付款条款', fields['payment_terms'])}{field('交期', fields['delivery_terms'])}
{field('装运港/发货地', fields['origin'])}{field('目的港/收货地', fields['destination'])}{field('运输方式', fields['shipping_method'])}{field('包装方式', fields['packing'])}
</section><h3>BANK / 收款信息</h3><section class="grid">{field('收款银行', fields['bank_name'])}{field('银行地址', fields['bank_address'])}{field('银行账号', fields['bank_account'])}{field('SWIFT/BIC', fields['swift_code'])}{field('收款人', fields['beneficiary'])}{extras}</section>
<h3>NOTES / 备注</h3><div class="notes">{h(fields['notes']) or '—'}</div>
<div class="footer">本页为可编辑模拟形式发票，金额与条款须人工确认。</div></div></body></html>'''


def export_invoice_pdf(invoice: dict) -> bytes:
    validate_invoice(invoice, complete=True)
    fields = invoice["fields"]
    amounts, subtotal, total = invoice_totals(invoice)
    # Embed a local CJK font so English labels and Chinese fields render consistently.
    font_path = Path("C:/Windows/Fonts/simhei.ttf")
    if font_path.is_file():
        font = "PI-SimHei"
        if font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font, str(font_path)))
    else:
        font = "STSong-Light"
        if font not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font))
    base = ParagraphStyle("pi-base", fontName=font, fontSize=9, leading=14, wordWrap="CJK", textColor=colors.HexColor("#263336"))
    small = ParagraphStyle("pi-small", parent=base, fontSize=8, leading=12)
    title = ParagraphStyle("pi-title", parent=base, fontSize=20, leading=26, textColor=colors.HexColor("#205a54"))
    subtitle = ParagraphStyle("pi-subtitle", parent=base, fontSize=10, leading=16)
    section = ParagraphStyle("pi-section", parent=base, fontSize=10, leading=17, textColor=colors.HexColor("#205a54"))
    right = ParagraphStyle("pi-right", parent=base, alignment=2)

    def para(value: str, style: ParagraphStyle = base) -> Paragraph:
        return Paragraph(xml_escape(value or "—").replace("\n", "<br/>"), style)

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
                            topMargin=17 * mm, bottomMargin=19 * mm, title=f"PI {fields['number']}")
    story = [para("PROFORMA INVOICE / 形式发票", title), para("SIMULATED DRAFT / 模拟草稿 · 正式使用前请逐项核对", small), Spacer(1, 6 * mm)]
    meta = Table([
        [para("PI NO. / 编号", small), para(fields["number"]), para("DATE / 日期", small), para(fields["issue_date"])],
        [para("VALID UNTIL / 有效期", small), para(fields["valid_until"]), "", ""],
    ], colWidths=[35 * mm, 55 * mm, 39 * mm, 47 * mm])
    meta.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf4f1")),
                              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 7),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([meta, Spacer(1, 6 * mm)])
    def party_cell(prefix: str, heading: str) -> list[Paragraph]:
        values = [fields[f"{prefix}_name"], fields[f"{prefix}_address"],
                  "  ".join(filter(None, (fields[f"{prefix}_contact"], fields[f"{prefix}_phone"]))),
                  fields[f"{prefix}_email"], fields[f"{prefix}_tax_id"]]
        return [para(heading, section)] + [para(value, small) for value in values if value.strip()]

    party = Table([[
        party_cell("seller", "SELLER / 卖方"), party_cell("buyer", "BUYER / 买方"),
    ]], colWidths=[88 * mm, 88 * mm])
    party.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, colors.HexColor("#d6e4de")),
                               ("INNERGRID", (0, 0), (-1, -1), .6, colors.HexColor("#d6e4de")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                               ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.extend([party, Spacer(1, 7 * mm), para("GOODS / 商品明细", section)])
    rows = [[para(value, small) for value in ("#", "品名 / 型号", "数量", "单位", "单价", "金额")]]
    for index, (item, amount) in enumerate(zip(invoice["items"], amounts), 1):
        description = item["description"] + ("\n" + item["model"] if item["model"].strip() else "")
        rows.append([para(str(index), small), para(description, small), para(item["quantity"], small),
                     para(item["unit"], small), para(money(Decimal(item["unit_price"].replace(",", ""))), small), para(money(amount), small)])
    goods = Table(rows, colWidths=[10 * mm, 74 * mm, 23 * mm, 18 * mm, 25 * mm, 26 * mm], repeatRows=1, hAlign="LEFT")
    goods.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f2ee")),
                               ("LINEBELOW", (0, 0), (-1, 0), .8, colors.HexColor("#abc9bf")),
                               ("LINEBELOW", (0, 1), (-1, -1), .3, colors.HexColor("#e4ebe7")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([goods, Spacer(1, 4 * mm)])
    totals = [[para("小计", right), para(money(subtotal), right)]]
    for key, label in (("freight", "运费"), ("insurance", "保险费"), ("discount", "折扣")):
        if fields[key].strip() and fields[key].strip() not in ("0", "0.00"):
            totals.append([para(label, right), para(fields[key], right)])
    totals.append([para("总金额 / TOTAL", right), para(f"{fields['currency']} {money(total)}", right)])
    total_table = Table(totals, colWidths=[55 * mm, 47 * mm], hAlign="RIGHT")
    total_table.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#78a99c")),
                                     ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.extend([total_table, Spacer(1, 7 * mm), para("TERMS / 条款", section)])
    term_rows = []
    for key, label in (("currency", "币种"), ("incoterm", "贸易条款"), ("payment_terms", "付款条款"),
                       ("delivery_terms", "交期"), ("origin", "装运港/发货地"), ("destination", "目的港/收货地"),
                       ("shipping_method", "运输方式"), ("packing", "包装方式"), ("bank_name", "收款银行"),
                       ("bank_address", "银行地址"), ("bank_account", "银行账号"),
                       ("swift_code", "SWIFT/BIC"), ("beneficiary", "收款人")):
        if fields[key].strip():
            term_rows.append([para(label, small), para(fields[key])])
    term_rows += [[para(term["label"], small), para(term["value"])] for term in invoice["extra_terms"] if term["label"].strip() and term["value"].strip()]
    if term_rows:
        terms = Table(term_rows, colWidths=[42 * mm, 134 * mm], hAlign="LEFT")
        terms.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#e4ebe7")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.append(terms)
    if fields["notes"].strip():
        story.extend([Spacer(1, 5 * mm), para("NOTES / 备注", section), para(fields["notes"])])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#899793"))
        canvas.drawString(17 * mm, 12 * mm, "SIMULATED DRAFT / 模拟形式发票 · 金额与条款须人工确认")
        canvas.drawRightString(A4[0] - 17 * mm, 12 * mm, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
