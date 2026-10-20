from __future__ import annotations

import io
import json
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from .invoice import validate_invoice
from .mail import validate_mail
from .models import normalize_positions, now_iso, validate_conversation

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000


class Store:
    def __init__(self, root: str | Path = "data"):
        self.root = Path(root).resolve()
        self.chats = self.root / "chats"
        self.assets = self.root / "assets"
        self.templates = self.root / "templates"
        self.emails = self.root / "emails"
        self.invoices = self.root / "invoices"
        for folder in (self.chats, self.assets, self.templates, self.emails, self.invoices):
            folder.mkdir(parents=True, exist_ok=True)

    def _path(self, folder: Path, identifier: str) -> Path:
        if not identifier or not all(c in "0123456789abcdef" for c in identifier) or len(identifier) != 32:
            raise ValueError("无效的资源或记录 ID。")
        return folder / f"{identifier}.json"

    def save(self, data: dict, *, template: bool = False, new_version: bool = False) -> dict:
        copy = json.loads(json.dumps(data, ensure_ascii=False))
        if new_version:
            copy["conversation_id"] = uuid4().hex
            copy["created_at"] = now_iso()
        copy["updated_at"] = now_iso()
        normalize_positions(copy)
        validate_conversation(copy)
        path = self._path(self.templates if template else self.chats, copy["conversation_id"])
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(copy, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
        return copy

    def load(self, identifier: str, *, template: bool = False) -> dict:
        path = self._path(self.templates if template else self.chats, identifier)
        try:
            with path.open(encoding="utf-8") as handle:
                return validate_conversation(json.load(handle))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"无法读取记录 {identifier}：{exc}") from exc

    def list_records(self, *, template: bool = False) -> list[dict]:
        folder = self.templates if template else self.chats
        records = []
        for path in folder.glob("*.json"):
            try:
                data = self.load(path.stem, template=template)
                records.append({"id": path.stem, "title": data["title"], "updated_at": data["updated_at"]})
            except ValueError:
                records.append({"id": path.stem, "title": "⚠ 损坏的记录", "updated_at": ""})
        return sorted(records, key=lambda item: item["updated_at"], reverse=True)

    def delete(self, identifier: str, *, template: bool = False) -> None:
        self._path(self.templates if template else self.chats, identifier).unlink()

    def save_mail(self, data: dict, *, new_version: bool = False) -> dict:
        copy = json.loads(json.dumps(data, ensure_ascii=False))
        validate_mail(copy)
        if new_version:
            copy["mail_id"] = uuid4().hex
            copy["created_at"] = now_iso()
        copy["updated_at"] = now_iso()
        path = self._path(self.emails, copy["mail_id"])
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(copy, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
        return copy

    def load_mail(self, identifier: str) -> dict:
        try:
            with self._path(self.emails, identifier).open(encoding="utf-8") as handle:
                return validate_mail(json.load(handle))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"无法读取邮件记录 {identifier}：{exc}") from exc

    def list_mail_records(self) -> list[dict]:
        records = []
        for path in self.emails.glob("*.json"):
            try:
                data = self.load_mail(path.stem)
                records.append({"id": path.stem, "title": data["subject"], "updated_at": data["updated_at"]})
            except ValueError:
                records.append({"id": path.stem, "title": "⚠ 损坏的邮件记录", "updated_at": ""})
        return sorted(records, key=lambda item: item["updated_at"], reverse=True)

    def delete_mail(self, identifier: str) -> None:
        self._path(self.emails, identifier).unlink()

    def save_invoice(self, data: dict, *, new_version: bool = False) -> dict:
        copy = json.loads(json.dumps(data, ensure_ascii=False))
        validate_invoice(copy)
        if new_version:
            copy["invoice_id"] = uuid4().hex
            copy["created_at"] = now_iso()
        copy["updated_at"] = now_iso()
        path = self._path(self.invoices, copy["invoice_id"])
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(copy, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
        return copy

    def load_invoice(self, identifier: str) -> dict:
        try:
            with self._path(self.invoices, identifier).open(encoding="utf-8") as handle:
                return validate_invoice(json.load(handle))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"无法读取 PI 记录 {identifier}：{exc}") from exc

    def list_invoice_records(self) -> list[dict]:
        records = []
        for path in self.invoices.glob("*.json"):
            try:
                data = self.load_invoice(path.stem)
                records.append({"id": path.stem, "title": data["fields"]["number"] or "未编号 PI",
                                "updated_at": data.get("updated_at", "")})
            except ValueError:
                records.append({"id": path.stem, "title": "⚠ 损坏的 PI 记录", "updated_at": ""})
        return sorted(records, key=lambda item: item["updated_at"], reverse=True)

    def delete_invoice(self, identifier: str) -> None:
        self._path(self.invoices, identifier).unlink()

    def save_image(self, uploaded: bytes) -> str:
        if not uploaded or len(uploaded) > MAX_IMAGE_BYTES:
            raise ValueError("图片不能为空且不能超过 8 MB。")
        try:
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            with Image.open(io.BytesIO(uploaded)) as source:
                source.verify()
            with Image.open(io.BytesIO(uploaded)) as source:
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise ValueError("图片像素过大。")
                image = source.convert("RGB")
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=True)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("只支持有效的图片文件。") from exc
        asset_id = uuid4().hex
        (self.assets / f"{asset_id}.png").write_bytes(output.getvalue())
        return asset_id

    def image_path(self, asset_id: str) -> Path:
        path = self._path(self.assets, asset_id).with_suffix(".png")
        if not path.is_file():
            raise ValueError(f"图片资源缺失：{asset_id}")
        return path
