from __future__ import annotations

import base64
import hmac
import json
import os
import urllib.request
from datetime import datetime
from hashlib import sha1
from typing import Any, Dict, Optional

from second_brain.config import load_config
from second_brain.core.pipeline import Pipeline, build_digest
from second_brain.registry import build_adapter


PROCESSED_IDS_PATH = "/tmp/webex_processed.json"
VALID_CATEGORIES = {"people", "projects", "ideas", "admin"}


def _verify_signature(secret: str, body: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), body, sha1).hexdigest()
    return hmac.compare_digest(expected, signature)


def _get_header(headers: Dict[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def _webex_get_message(message_id: str, token: str) -> Dict[str, Any]:
    url = f"https://webexapis.com/v1/messages/{message_id}"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _webex_post_message(room_id: str, token: str, text: str) -> None:
    url = "https://webexapis.com/v1/messages"
    payload = json.dumps({"roomId": room_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request) as response:
        response.read()


def _load_processed_ids() -> set[str]:
    if not os.path.exists(PROCESSED_IDS_PATH):
        return set()
    try:
        with open(PROCESSED_IDS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return set(data)
    except (json.JSONDecodeError, OSError):
        return set()


def _save_processed_ids(ids: set[str]) -> None:
    with open(PROCESSED_IDS_PATH, "w", encoding="utf-8") as handle:
        json.dump(sorted(ids), handle)


def _parse_fix_category(text: str) -> str | None:
    if not text.lower().startswith("fix:"):
        return None
    remainder = text.split(":", 1)[1].strip().lower()
    if not remainder:
        return None
    token = remainder.split()[0]
    if token in ("person", "people"):
        return "people"
    if token in ("project", "projects"):
        return "projects"
    if token in ("idea", "ideas"):
        return "ideas"
    if token == "admin":
        return "admin"
    return None


def _parse_command(text: str) -> str | None:
    cleaned = _strip_bot_prefix(text).strip().lower()
    if not cleaned:
        return None
    cleaned = cleaned.replace("?", "").replace("!", "").strip()
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return None
    if tokens == ["help"] or tokens == ["commands"] or tokens == ["?"]:
        return "help"
    if tokens == ["this", "week"]:
        return "week"
    if tokens == ["next"]:
        return "next"
    if tokens == ["today"] or tokens == ["daily"]:
        return "today"
    if tokens == ["week"] or tokens == ["weekly"]:
        return "week"
    return None


def _strip_bot_prefix(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    bot_name = os.environ.get("WEBEX_BOT_NAME", "").strip().lower()
    lower = cleaned.lower()
    if bot_name:
        for prefix in (bot_name, f"@{bot_name}"):
            if lower.startswith(prefix + " "):
                return cleaned[len(prefix) + 1 :]
            if lower.startswith(prefix + ":"):
                return cleaned[len(prefix) + 1 :]
    for prefix in ("task_master", "taskmanager", "task manager", "bot"):
        for variant in (prefix, f"@{prefix}"):
            if lower.startswith(variant + " "):
                return cleaned[len(variant) + 1 :]
            if lower.startswith(variant + ":"):
                return cleaned[len(variant) + 1 :]
    return cleaned


def _enqueue_text(text: str) -> None:
    config = load_config()
    capture = build_adapter(config.capture.class_path, config.capture.settings)
    if not hasattr(capture, "enqueue"):
        raise RuntimeError("Capture adapter does not support enqueue().")
    capture.enqueue(text, source="webex", created_at=datetime.utcnow())


def _run_pipeline(room_id: Optional[str] = None) -> int:
    config = load_config()
    capture = build_adapter(config.capture.class_path, config.capture.settings)
    ai = build_adapter(config.ai.class_path, config.ai.settings)
    storage = build_adapter(config.storage.class_path, config.storage.settings)
    notifier_settings = dict(config.notifier.settings)
    if config.notifier.class_path.endswith("notifier_webex.WebexNotifier"):
        if room_id:
            notifier_settings["room_id"] = room_id
        if not notifier_settings.get("token"):
            token = os.environ.get("WEBEX_BOT_TOKEN")
            if token:
                notifier_settings["token"] = token
    notifier = build_adapter(config.notifier.class_path, notifier_settings)
    pipeline = Pipeline(
        capture=capture,
        ai=ai,
        storage=storage,
        notifier=notifier,
        confidence_threshold=config.confidence_threshold,
    )
    stored = pipeline.run()
    return len(stored)


def _run_digest(digest_type: str, room_id: str, days: int, title: str, weekly: bool) -> None:
    config = load_config()
    storage = build_adapter(config.storage.class_path, config.storage.settings)
    notifier_settings = dict(config.notifier.settings)
    if config.notifier.class_path.endswith("notifier_webex.WebexNotifier"):
        notifier_settings["room_id"] = room_id
        if not notifier_settings.get("token"):
            token = os.environ.get("WEBEX_BOT_TOKEN")
            if token:
                notifier_settings["token"] = token
    notifier = build_adapter(config.notifier.class_path, notifier_settings)
    if os.environ.get("SB_EXTRACTIVE_DIGESTS", "true").lower() == "true":
        records = storage.list_records(categories=["projects", "people", "ideas", "admin"], days=days)
        lines = []
        for record in records[:20]:
            fields = record.fields or {}
            if record.category == "projects":
                context = fields.get("Next Action") or fields.get("next_action") or fields.get("Notes") or fields.get("notes")
            elif record.category == "people":
                context = fields.get("Context") or fields.get("context") or fields.get("Follow Ups") or fields.get("follow_ups")
            elif record.category == "ideas":
                context = fields.get("One Liner") or fields.get("one_liner") or fields.get("Notes") or fields.get("notes")
            else:
                context = fields.get("Notes") or fields.get("notes")
            if context:
                lines.append(f"- {record.category}: {record.title} — {context}")
            else:
                lines.append(f"- {record.category}: {record.title}")
        body = "\n".join(lines) if lines else "No items found."
        notifier.notify_digest(f"{title}\n{body}")
        return
    ai = build_adapter(config.ai.class_path, config.ai.settings)
    build_digest(
        ai=ai,
        storage=storage,
        notifier=notifier,
        categories=["projects", "people", "ideas", "admin"],
        days=days,
        title=title,
        weekly=weekly,
    )


def handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    digest_type = event.get("digest") or event.get("detail", {}).get("digest")
    if digest_type in {"daily", "weekly"}:
        room_id = os.environ.get("WEBEX_DIGEST_ROOM_ID", "")
        if not room_id:
            return {"statusCode": 500, "body": "missing WEBEX_DIGEST_ROOM_ID"}
        if digest_type == "weekly":
            _run_digest(digest_type, room_id, days=7, title="[SB DIGEST] Weekly Review", weekly=True)
        else:
            _run_digest(digest_type, room_id, days=1, title="[SB DIGEST] Daily Digest", weekly=False)
        return {"statusCode": 200, "body": f"{digest_type} digest sent"}
    if event.get("httpMethod") == "GET":
        return {"statusCode": 200, "body": "ok"}

    body = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        body_bytes = base64.b64decode(body)
    else:
        body_bytes = body.encode("utf-8")

    headers = event.get("headers", {}) or {}
    secret = os.environ.get("WEBEX_WEBHOOK_SECRET")
    if secret:
        signature = _get_header(headers, "X-Spark-Signature")
        if not signature or not _verify_signature(secret, body_bytes, signature):
            print("Invalid webhook signature")
            return {"statusCode": 401, "body": "invalid signature"}

    payload = json.loads(body_bytes.decode("utf-8"))
    data = payload.get("data", {})
    if payload.get("resource") != "messages" or payload.get("event") != "created":
        print(f"Ignoring event: resource={payload.get('resource')} event={payload.get('event')}")
        return {"statusCode": 200, "body": "ignored"}

    token = os.environ.get("WEBEX_BOT_TOKEN")
    if not token:
        print("Missing WEBEX_BOT_TOKEN")
        return {"statusCode": 500, "body": "missing WEBEX_BOT_TOKEN"}

    message_id = data.get("id")
    if not message_id:
        print("Missing message id")
        return {"statusCode": 200, "body": "missing message id"}

    message = _webex_get_message(message_id, token)
    bot_email = os.environ.get("WEBEX_BOT_EMAIL")
    bot_id = os.environ.get("WEBEX_BOT_ID")
    if message.get("personType") == "bot":
        return {"statusCode": 200, "body": "ignored bot"}
    if bot_email and message.get("personEmail") == bot_email:
        return {"statusCode": 200, "body": "ignored bot"}
    if bot_id and message.get("personId") == bot_id:
        return {"statusCode": 200, "body": "ignored bot"}
    if message.get("personEmail", "").endswith("@webex.bot"):
        return {"statusCode": 200, "body": "ignored bot"}

    room_id = message.get("roomId")
    text = (message.get("text") or "").strip()
    if not text:
        return {"statusCode": 200, "body": "empty message"}
    if text.startswith(("[SB DIGEST]", "Filed as", "Needs review", "Daily Digest", "Weekly Review")):
        return {"statusCode": 200, "body": "ignored system message"}

    command = _parse_command(text)
    if command:
        if command == "help":
            _webex_post_message(
                room_id,
                token,
                "[SB HELP]\\nCommands: next | today | week | help\\nPrefixes: person:, project:, idea:, admin:\\nFix replies: fix: person|project|idea|admin",
            )
            return {"statusCode": 200, "body": "help sent"}
        if command == "week":
            _run_digest("weekly", room_id, days=7, title="[SB DIGEST] This Week", weekly=True)
            return {"statusCode": 200, "body": "weekly digest sent"}
        if command == "today":
            _run_digest("daily", room_id, days=1, title="[SB DIGEST] Today", weekly=False)
            return {"statusCode": 200, "body": "daily digest sent"}
        _run_digest("next", room_id, days=14, title="[SB DIGEST] Next Focus", weekly=False)
        return {"statusCode": 200, "body": "next digest sent"}

    fix_category = _parse_fix_category(text)
    if fix_category:
        parent_id = message.get("parentId")
        if not parent_id:
            return {"statusCode": 200, "body": "fix missing parent"}
        original = _webex_get_message(parent_id, token)
        original_text = (original.get("text") or "").strip()
        if not original_text:
            return {"statusCode": 200, "body": "fix missing original text"}
        _enqueue_text(f"{fix_category}: {original_text}")
        processed = 0
        if os.environ.get("SB_RUN_PIPELINE", "true").lower() == "true":
            processed = _run_pipeline(room_id=room_id)
        return {"statusCode": 200, "body": json.dumps({"status": "fixed", "processed": processed})}

    processed_ids = _load_processed_ids()
    if message_id not in processed_ids:
        processed_ids.add(message_id)
        _save_processed_ids(processed_ids)

    _enqueue_text(text)
    processed = 0
    if os.environ.get("SB_RUN_PIPELINE", "true").lower() == "true":
        processed = _run_pipeline(room_id=room_id)

    return {
        "statusCode": 200,
        "body": json.dumps({"status": "queued", "processed": processed}),
    }
