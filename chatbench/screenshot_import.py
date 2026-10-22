"""Local OCR drafts for importing chat screenshots into the message editor."""

from __future__ import annotations

import io
import re
from functools import lru_cache
from statistics import median

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
TIME_LABEL = re.compile(r"^(?:(?:今天|昨天|Today|Yesterday)\s*)?(?:\d{1,2}:\d{2}|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(?:日)?(?:\s+\d{1,2}:\d{2})?)$", re.I)


@lru_cache(maxsize=1)
def _ocr_engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError("本机缺少截图识别组件，请安装 requirements.txt 中的 OCR 依赖。") from exc
    return RapidOCR()


def _side(left: float, right: float, width: int, text: str) -> str:
    if TIME_LABEL.fullmatch(text.strip()):
        return ""
    line_width = right - left
    if line_width < width * 0.42 and abs((left + right) / 2 - width / 2) < width * 0.09:
        return ""
    return "seller" if left > width - right else "buyer"


def _join_lines(first: str, second: str) -> str:
    if first.endswith(("-", "‐")) and second[:1].isascii():
        return first[:-1] + second
    if ("\u4e00" <= first[-1:] <= "\u9fff") and ("\u4e00" <= second[:1] <= "\u9fff"):
        return first + second
    return first + " " + second


def extract_chat_draft(uploaded: bytes) -> list[dict]:
    """Return editable OCR message candidates; never persists the source image."""
    if not uploaded or len(uploaded) > MAX_UPLOAD_BYTES:
        raise ValueError("请上传不超过 15 MB 的聊天截图。")
    try:
        with Image.open(io.BytesIO(uploaded)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("截图像素过大，请裁剪后重试。")
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("无法读取截图，请使用 PNG、JPG 或 WebP 图片。") from exc

    result = _ocr_engine()(image)
    if result.boxes is None or not result.txts:
        return []
    lines = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        text = str(text).strip()
        if not text:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
        lines.append({"text": text, "left": left, "right": right, "top": top,
                      "bottom": bottom, "score": float(score),
                      "sender": _side(left, right, image.width, text)})
    lines.sort(key=lambda line: (line["top"], line["left"]))

    draft = []
    for line in lines:
        if (draft and line["sender"] and draft[-1]["sender"] == line["sender"]
                and line["top"] - draft[-1]["bottom"] <= max(7, (line["bottom"] - line["top"]) * 0.8)
                and abs(line["left"] - draft[-1]["left"]) <= max(28, image.width * 0.06)):
            current = draft[-1]
            current["text"] = _join_lines(current["text"], line["text"])
            current["bottom"] = max(current["bottom"], line["bottom"])
            current["score"] = min(current["score"], line["score"])
        else:
            draft.append(line.copy())
    return [{"导入": bool(item["sender"]), "发送方": item["sender"], "消息文本": item["text"],
             "识别可信度": round(item["score"], 2)} for item in draft]


def inspect_appearance(uploaded: bytes) -> dict:
    """Suggest a palette and header from the screenshot; all values need user review."""
    with Image.open(io.BytesIO(uploaded)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    width, height = image.size
    result = _ocr_engine()(image)
    names = []
    bubble_pixels = {"buyer": [], "seller": []}
    if result.boxes is not None and result.txts:
        for box, value in zip(result.boxes, result.txts):
            top = min(float(point[1]) for point in box)
            left = min(float(point[0]) for point in box)
            right = max(float(point[0]) for point in box)
            bottom = max(float(point[1]) for point in box)
            name = str(value).strip()
            if top < height * 0.16 and name and not TIME_LABEL.fullmatch(name):
                names.append((top, name))
            side = _side(left, right, width, name)
            if side and height * .16 <= top <= height * .9:
                sample_x = left - 5 if side == "buyer" else right + 5
                if 0 <= sample_x < width:
                    bubble_pixels[side].append(image.getpixel((int(sample_x), int((top + bottom) / 2))))
    names.sort()

    def color(pixel: tuple[int, int, int]) -> str:
        return "#%02x%02x%02x" % pixel

    def typical(pixels: list[tuple[int, int, int]], fallback: tuple[int, int, int]) -> str:
        if not pixels:
            return color(fallback)
        return color(tuple(int(median(pixel[channel] for pixel in pixels)) for channel in range(3)))

    edge_pixels = [image.getpixel((max(0, int(width * .01)), y))
                   for y in range(int(height * .2), int(height * .85), max(1, height // 40))]

    # These locations are only suggestions. The review controls allow correction.
    return {
        "header_name": names[0][1] if names else "",
        "background": typical(edge_pixels, (248, 244, 238)),
        "incoming": typical(bubble_pixels["buyer"], (255, 255, 255)),
        "outgoing": typical(bubble_pixels["seller"], (217, 253, 211)),
        "font_size": 14,
        "image_width": width,
        "image_height": height,
    }


def crop_avatar(uploaded: bytes, x: int, y: int, size: int) -> bytes:
    with Image.open(io.BytesIO(uploaded)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    if size < 8 or x < 0 or y < 0 or x + size > image.width or y + size > image.height:
        raise ValueError("头像裁剪区域超出截图边界。")
    output = io.BytesIO()
    image.crop((x, y, x + size, y + size)).save(output, format="PNG")
    return output.getvalue()
