from __future__ import annotations

import io
import re
import zipfile

from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError

from .models import validate_conversation
from .renderer import render_html
from .storage import Store


def safe_filename(title: str, identifier: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_")[:45]
    return f"{clean or 'chat'}_{identifier[:8]}.png"


def export_png(data: dict, store: Store, *, scale: int = 3) -> bytes:
    validate_conversation(data)
    if scale not in (1, 2, 3):
        raise ValueError("PNG 清晰度仅支持 1–3 倍。")
    html = render_html(data, store)
    width = max(420, min(1000, int(data.get("render_settings", {}).get("width", 620))))
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as first_error:
            try:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
            except PlaywrightError as second_error:
                raise RuntimeError("无法启动截图浏览器。请运行 python -m playwright install chromium，或安装 Chrome。") from second_error
        try:
            page = browser.new_page(viewport={"width": width, "height": 800}, device_scale_factor=scale)
            page.set_content(html, wait_until="load")
            page.evaluate("document.fonts.ready")
            page.locator("img").evaluate_all("imgs => Promise.all(imgs.map(img => img.complete ? Promise.resolve() : new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject })))")
            frame = page.locator(".frame")
            result = frame.screenshot(type="png", animations="disabled", timeout=30000)
            page.close()
            return result
        finally:
            browser.close()


def export_zip(results: list[dict], store: Store, *, scale: int = 3) -> tuple[bytes, dict[str, str]]:
    output = io.BytesIO()
    errors = {}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in results:
            data = item["data"]
            try:
                archive.writestr(safe_filename(data["title"], data["conversation_id"]), export_png(data, store, scale=scale))
            except Exception as exc:
                errors[data["conversation_id"]] = str(exc)
    return output.getvalue(), errors
