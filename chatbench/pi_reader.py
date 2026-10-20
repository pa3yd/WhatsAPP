from __future__ import annotations

import io
import re

from pypdf import PdfReader

MAX_PI_BYTES = 10 * 1024 * 1024
MAX_PI_PAGES = 10

FIELD_LABELS = {
    "number": "PI 编号", "date": "PI 日期", "seller": "卖方", "buyer": "买方",
    "product": "产品与规格", "quantity": "数量", "unit_price": "单价",
    "total": "总金额", "currency": "币种", "incoterm": "贸易条款",
    "payment": "付款条款", "delivery": "交期", "shipping": "运输信息",
}

PATTERNS = {
    "number": r"(?:proforma\s+invoice\s*(?:no\.?|number|#)?|PI\s*(?:no\.?|number|#))\s*[:：#-]?\s*(.+)",
    "date": r"(?:invoice\s+date|PI\s+date|日期)\s*[:：-]?\s*(.+)",
    "seller": r"(?:seller|exporter|供应商|卖方)\s*[:：-]?\s*(.+)",
    "buyer": r"(?:buyer|bill\s+to|customer|买方|客户)\s*[:：-]?\s*(.+)",
    "product": r"(?:description\s+of\s+goods|product\s+description|产品名称|品名)\s*[:：-]?\s*(.+)",
    "quantity": r"(?:total\s+quantity|quantity|qty|数量)\s*[:：-]?\s*(.+)",
    "unit_price": r"(?:unit\s+price|单价)\s*[:：-]?\s*(.+)",
    "total": r"(?:grand\s+total|total\s+amount|invoice\s+total|总金额|合计金额)\s*[:：-]?\s*(.+)",
    "currency": r"(?:currency|币种)\s*[:：-]?\s*(.+)",
    "incoterm": r"(?:incoterms?|trade\s+terms?|贸易条款)\s*[:：-]?\s*(.+)",
    "payment": r"(?:payment\s+terms?|付款条款|付款方式)\s*[:：-]?\s*(.+)",
    "delivery": r"(?:delivery\s+time|lead\s+time|delivery\s+date|交期|交货期)\s*[:：-]?\s*(.+)",
    "shipping": r"(?:port\s+of\s+loading|port\s+of\s+discharge|shipping\s+method|装运港|目的港)\s*[:：-]?\s*(.+)",
}


def extract_pi(pdf_bytes: bytes) -> tuple[dict[str, str], str, int]:
    """Extract tentative values from a text PDF; never treat them as verified facts."""
    if not pdf_bytes or len(pdf_bytes) > MAX_PI_BYTES:
        raise ValueError("PI PDF 不能为空且不能超过 10 MB。")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("请上传有效的 PDF 文件。")
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        if reader.is_encrypted:
            raise ValueError("加密 PDF 暂不支持，请先提供可读取的副本。")
        if not 1 <= len(reader.pages) <= MAX_PI_PAGES:
            raise ValueError("PI PDF 须为 1–10 页。")
        text = "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF 无法读取或文本提取失败。") from exc
    if not text.strip():
        raise ValueError("PDF 没有可复制文字；扫描件或图片目前无法本地识别。")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    fields = {field: "" for field in FIELD_LABELS}
    for line in lines:
        for field, pattern in PATTERNS.items():
            if fields[field]:
                continue
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                fields[field] = match.group(1).strip()[:300]
    return fields, text[:30000], len(reader.pages)
