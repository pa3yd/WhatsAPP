from __future__ import annotations

import json
import os

from .models import new_message, normalize_positions, uid
from .time_engine import assign_times

LANGUAGE_SAMPLES = {
    "法语": ["Bonjour, je cherche un chargeur pour téléphone.", "Bonjour ! Quel type de chargeur vous intéresse ?", "Pouvez-vous préciser les caractéristiques et le délai ?", "Bien sûr. Je peux préparer une fiche produit pour vous.", "Merci. Avez-vous une photo du produit ?", "Oui, je peux partager une image de démonstration.", "Quel est le minimum de commande ?", "Je vais vérifier cette information avant de vous répondre.", "Très bien, merci pour votre aide.", "Avec plaisir, restons en contact."],
    "英语": ["Hello, I am looking for a phone charger.", "Hello! What specifications do you need?", "Could you share the product details?", "Of course. I can prepare a product sheet.", "Do you have an example image?", "Yes, I can share a demonstration image.", "What is the minimum order quantity?", "I will confirm that before quoting.", "Thank you, that sounds good.", "You're welcome. Let's stay in touch."],
    "西班牙语": ["Hola, busco un cargador de teléfono.", "¡Hola! ¿Qué especificaciones necesita?", "¿Puede compartir los detalles del producto?", "Por supuesto, prepararé una ficha del producto.", "¿Tiene una imagen de ejemplo?", "Sí, puedo compartir una imagen de demostración.", "¿Cuál es el pedido mínimo?", "Lo confirmaré antes de ofrecer un precio.", "Gracias, perfecto.", "Con gusto, seguimos en contacto."],
    "德语": ["Guten Tag, ich suche ein Handy-Ladegerät.", "Guten Tag! Welche Anforderungen haben Sie?", "Können Sie die Produktdaten senden?", "Gerne, ich bereite ein Datenblatt vor.", "Haben Sie ein Beispielbild?", "Ja, ich kann ein Demobild teilen.", "Wie hoch ist die Mindestbestellmenge?", "Das prüfe ich vor einem Angebot.", "Vielen Dank.", "Gern geschehen, wir bleiben in Kontakt."],
    "中文": ["您好，我想了解手机充电器。", "您好，请问您需要什么规格？", "可以提供产品参数吗？", "可以，我会整理产品资料。", "有产品示意图吗？", "有，我可以分享模拟展示图片。", "最小起订量是多少？", "我确认后再给您准确答复。", "谢谢，期待回复。", "好的，保持联系。"],
}


def offline_sample(data: dict, count: int) -> dict:
    """Clearly labeled editable sample, never presented as AI output."""
    lines = LANGUAGE_SAMPLES.get(data["language"], LANGUAGE_SAMPLES["英语"])
    data["messages"] = []
    for i in range(count):
        msg = new_message("buyer" if i % 2 == 0 else "seller", lines[i % len(lines)])
        msg["source"] = "offline_sample"
        data["messages"].append(msg)
    normalize_positions(data)
    assign_times(data)
    return data


def _schema(count: int) -> dict:
    return {"type": "object", "properties": {"messages": {"type": "array", "items": {"type": "object", "properties": {"sender_id": {"type": "string", "enum": ["buyer", "seller"]}, "text": {"type": "string"}}, "required": ["sender_id", "text"], "additionalProperties": False}}}, "required": ["messages"], "additionalProperties": False}


def _call_model(prompt: str, count: int) -> list[dict]:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError("未配置 OPENAI_API_KEY；可继续使用完全手动模式或离线示例。")
    from openai import OpenAI

    client = OpenAI(timeout=60)
    response = client.responses.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        instructions="Create a fictional business chat for training. Return only the requested JSON. Do not claim that it is a real WhatsApp conversation. Do not invent verified specifications, prices or commitments.",
        input=prompt,
        text={"format": {"type": "json_schema", "name": "chat_messages", "strict": True, "schema": _schema(count)}},
        store=False,
    )
    if response.status != "completed" or not response.output_text:
        raise RuntimeError("模型未返回完整聊天内容。")
    parsed = json.loads(response.output_text)["messages"]
    if len(parsed) != count or any(not isinstance(item.get("text"), str) for item in parsed):
        raise RuntimeError(f"模型返回 {len(parsed)} 条消息，预期 {count} 条；请重试。")
    return parsed


def generate_ai(data: dict, count: int) -> dict:
    prompt = json.dumps({
        "task": f"Write exactly {count} alternating buyer/seller messages. User may edit afterward.",
        "country": data["country"], "language": data["language"], "tone": data["tone"],
        "goal": data["goal"], "participants": data["participants"], "product": {k: v for k, v in data["product"].items() if k != "image_ids"},
        "required_keywords": data["keywords"]["required"], "forbidden_keywords": data["keywords"]["forbidden"],
        "allow_details": data["allow_details"],
    }, ensure_ascii=False)
    items = _call_model(prompt, count)
    messages = []
    for item in items:
        msg = new_message(item["sender_id"], item["text"])
        msg["source"] = "ai"
        messages.append(msg)
    data["messages"] = messages
    normalize_positions(data)
    assign_times(data)
    return data


def regenerate_one(data: dict, message_id: str) -> None:
    index = next((i for i, item in enumerate(data["messages"]) if item["id"] == message_id), None)
    if index is None:
        raise ValueError("消息不存在。")
    old = data["messages"][index]
    if old.get("locked"):
        raise ValueError("该消息已锁定。")
    context = [{"sender_id": m["sender_id"], "text": m["text"]} for m in data["messages"][max(0, index - 3): index + 4]]
    prompt = json.dumps({"task": "Rewrite only the target message. Keep sender and context coherent. Return exactly one message.", "target_index": min(3, index), "context": context, "language": data["language"], "tone": data["tone"], "product": data["product"]["name"], "forbidden_keywords": data["keywords"]["forbidden"]}, ensure_ascii=False)
    replacement = _call_model(prompt, 1)[0]
    old["text"] = replacement["text"]
    old["source"] = "ai"


def clone_for_batch(source: dict, *, country: str, language: str, timezone: str, buyer: str, seller: str, count: int) -> dict:
    copy = json.loads(json.dumps(source, ensure_ascii=False))
    copy["conversation_id"] = uid()
    copy["country"], copy["language"], copy["timezone"] = country, language, timezone
    copy["title"] = f"{country} · {copy['product']['name']} · 模拟对话"
    copy["participants"]["buyer"]["name"] = buyer
    copy["participants"]["seller"]["name"] = seller
    copy["messages"] = []
    return offline_sample(copy, count)
