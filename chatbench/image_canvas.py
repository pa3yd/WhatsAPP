"""Edit OCR text regions on an uploaded screenshot while retaining its pixels."""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .screenshot_import import MAX_IMAGE_PIXELS, MAX_UPLOAD_BYTES, _ocr_engine, _side


def _open(uploaded: bytes) -> Image.Image:
    if not uploaded or len(uploaded) > MAX_UPLOAD_BYTES:
        raise ValueError("请上传不超过 15 MB 的截图。")
    with Image.open(io.BytesIO(uploaded)) as source:
        if source.width * source.height > MAX_IMAGE_PIXELS:
            raise ValueError("截图像素过大，请先裁剪。")
        return ImageOps.exif_transpose(source).convert("RGB")


def detect_regions(uploaded: bytes) -> list[dict]:
    """Return OCR text boxes for review; positions refer to original pixels."""
    image = _open(uploaded)
    result = _ocr_engine()(image)
    if result.boxes is None or not result.txts:
        return []
    rows = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        text = str(text).strip()
        if not text:
            continue
        xs = [int(round(point[0])) for point in box]
        ys = [int(round(point[1])) for point in box]
        x, y = max(0, min(xs)), max(0, min(ys))
        width, height = max(xs) - x, max(ys) - y
        if width < 3 or height < 3:
            continue
        rows.append({"编号": len(rows) + 1, "操作": "保留", "内容": text,
                     "X": x, "Y": y, "宽": width, "高": height,
                     "方向": "右" if _side(x, x + width, image.width, text) == "seller" else "左",
                     "可信度": round(float(score), 2)})
    return sorted(rows, key=lambda row: (row["Y"], row["X"]))


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/simsun.ttc"),
                 Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, width: int, height: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for size in range(min(34, max(10, height)), 7, -1):
        font = _font(size)
        bounds = draw.multiline_textbbox((0, 0), text, font=font, spacing=2)
        if bounds[2] <= width and bounds[3] - bounds[1] <= height:
            return font
    raise ValueError("新文字超出选定区域；请缩短文字或增大该行的宽、高。")


def _color_near(image: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return image.getpixel((min(image.width - 1, max(0, x)), min(image.height - 1, max(0, y))))


def _bubble_rect(image: Image.Image, source: dict) -> tuple[int, int, int, int] | None:
    """Find a flat bubble around an OCR box; return None if no safe region is found."""
    x, y, width, height = (int(source[field]) for field in ("X", "Y", "宽", "高"))
    pixels = np.array(image)
    background = np.array(_color_near(image, 1, y + height // 2), dtype=np.int16)
    for sx, sy in ((x - 5, y - 5), (x + width + 5, y - 5), (x - 5, y + height + 5)):
        if not (0 <= sx < image.width and 0 <= sy < image.height):
            continue
        candidate = pixels[sy, sx].astype(np.int16)
        if np.max(np.abs(candidate - background)) < 14:
            continue
        mask = np.zeros((image.height + 2, image.width + 2), dtype=np.uint8)
        _, _, _, (rx, ry, rw, rh) = cv2.floodFill(pixels.copy(), mask, (sx, sy), (0, 0, 0),
            loDiff=(12, 12, 12), upDiff=(12, 12, 12), flags=cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8))
        if (rw >= width * .8 and rh >= height * .8 and rw * rh < image.width * image.height * .3
                and rx <= x + 3 and ry <= y + 3 and rx + rw >= x + width - 3 and ry + rh >= y + height - 3):
            return rx, ry, rw, rh
    return None


def render_image_edit(uploaded: bytes, original: list[dict], edited: list[dict]) -> bytes:
    """Return a PNG; original bytes are never modified or saved by this function."""
    image = _open(uploaded)
    baseline = image.copy()
    original_by_id = {row["编号"]: row for row in original}
    operations = []
    kept_ids = {row.get("编号") for row in edited if row.get("编号") in original_by_id}
    for identifier, source in original_by_id.items():
        if identifier not in kept_ids:
            operations.append(("删除", source, 0, 0, 4, 4, "", None))
    for row in edited:
        action = str(row.get("操作") or "保留")
        if action == "保留":
            continue
        if action not in ("修改", "删除", "新增"):
            raise ValueError("操作只能是保留、修改、删除或新增。")
        identifier = row.get("编号")
        source = original_by_id.get(identifier)
        if action != "新增" and source is None:
            raise ValueError("修改或删除需要选择一条已识别的原图文字。")
        try:
            x, y, width, height = (int(row[field]) for field in ("X", "Y", "宽", "高"))
        except (TypeError, ValueError) as exc:
            raise ValueError("请为编辑区域填写有效的 X、Y、宽、高。") from exc
        if x < 0 or y < 0 or width < 4 or height < 4 or x + width > image.width or y + height > image.height:
            raise ValueError("编辑区域必须位于原图内，宽和高至少为 4 像素。")
        content = str(row.get("内容") or "").strip()
        if action != "删除" and not content:
            raise ValueError("修改或新增的文字不能为空。")
        operations.append((action, source, x, y, width, height, content, row.get("方向")))

    mask = np.zeros((image.height, image.width), dtype=np.uint8)
    for action, source, _, _, _, _, _, _ in operations:
        if source is None:
            continue
        bubble = _bubble_rect(baseline, source) if action == "删除" else None
        ox, oy, ow, oh = bubble or tuple(int(source[field]) for field in ("X", "Y", "宽", "高"))
        padding = 2 if bubble else 9 if action == "删除" else 3
        cv2.rectangle(mask, (max(0, ox - padding), max(0, oy - padding)),
                      (min(image.width - 1, ox + ow + padding), min(image.height - 1, oy + oh + padding)), 255, -1)
    if np.any(mask):
        image = Image.fromarray(cv2.inpaint(np.array(image), mask, 7, cv2.INPAINT_TELEA))
    draw = ImageDraw.Draw(image)
    for action, source, x, y, width, height, content, direction in operations:
        if action == "删除":
            continue
        if action == "新增":
            fill = (220, 247, 214) if direction == "右" else (242, 242, 242)
            draw.rounded_rectangle((x - 7, y - 5, x + width + 7, y + height + 5), radius=7, fill=fill)
        elif source is not None:
            fill = _color_near(baseline, int(source["X"]) - 5, int(source["Y"]) + int(source["高"]) // 2)
            draw.rectangle((x - 2, y - 2, x + width + 2, y + height + 2), fill=fill)
        font = _fit_font(draw, content, width, height)
        draw.multiline_text((x, y), content, fill=(20, 20, 20), font=font, spacing=2)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def annotated_image(uploaded: bytes, rows: list[dict]) -> bytes:
    image = _open(uploaded)
    draw = ImageDraw.Draw(image)
    for row in rows:
        x, y, width, height = (int(row[field]) for field in ("X", "Y", "宽", "高"))
        draw.rectangle((x - 2, y - 2, x + width + 2, y + height + 2), outline="#ef4444", width=2)
        draw.text((x, max(0, y - 18)), str(row["编号"]), fill="#d00000", font=_font(13))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
