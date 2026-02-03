from __future__ import annotations

import base64
import hmac
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Dict, Optional

from second_brain.config import load_config
from second_brain.core.pipeline import Pipeline, build_digest
from second_brain.core.models import StoredRecord
from second_brain.registry import build_adapter


PROCESSED_IDS_PATH = "/tmp/webex_processed.json"
STATE_PATH = "/tmp/webex_state.json"
VALID_CATEGORIES = {"people", "projects", "ideas", "admin"}
CATEGORIES = ["projects", "people", "ideas", "admin"]
LIST_LIMIT = 20
STATE_TTL_MINUTES = 30
COMPLETED_STATUSES = {"done", "completed", "complete", "closed", "archived"}


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
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _webex_post_message(room_id: str, token: str, text: str) -> None:
    url = "https://webexapis.com/v1/messages"
    payload = json.dumps({"roomId": room_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=8) as response:
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


def _load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def _prune_state(state: dict) -> dict:
    cutoff = datetime.now(timezone.utc).timestamp() - (STATE_TTL_MINUTES * 60)
    for room_id, room_state in list(state.items()):
        for person_id, data in list(room_state.items()):
            updated_at = data.get("updated_at", 0)
            if updated_at and updated_at < cutoff:
                room_state.pop(person_id, None)
        if not room_state:
            state.pop(room_id, None)
    return state


def _parse_fix_category(text: str) -> str | None:
    if not text.lower().startswith("fix:"):
        return None
    remainder = text.split(":", 1)[1].strip().lower()
    if not remainder:
        return None
    token = remainder.split()[0]
    mapping = {
        "person": "people",
        "people": "people",
        "project": "projects",
        "projects": "projects",
        "idea": "ideas",
        "ideas": "ideas",
        "admin": "admin",
    }
    return mapping.get(token)


def _parse_command(text: str) -> str | None:
    cleaned = _strip_bot_prefix(text).strip().lower()
    if not cleaned:
        return None
    cleaned = cleaned.replace("?", "").replace("!", "").strip()
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return None
    if tokens == ["help"] or tokens == ["commands"]:
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


def _parse_update_request(text: str) -> int | None:
    cleaned = _strip_bot_prefix(text).strip().lower()
    if not cleaned.startswith("update"):
        return None
    remainder = cleaned[len("update") :].strip()
    if remainder.startswith(":"):
        remainder = remainder[1:].strip()
    match = re.match(r"^(\d+)\b", remainder)
    if not match:
        return None
    return int(match.group(1))


def _parse_field_selection(text: str) -> tuple[int | None, str | None]:
    cleaned = _strip_bot_prefix(text).strip()
    match = re.match(r"^(\d+)(?:[\).:\-]\s*|\s+)?(.*)$", cleaned)
    if not match:
        return None, None
    number = int(match.group(1))
    value = match.group(2).strip()
    return number, value or None


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
        if days == 1:
            records = _select_daily_records(storage, days=days)
        else:
            records = storage.list_records(categories=CATEGORIES, days=days)
            records.sort(key=lambda r: (_priority_value(r), r.created_at))
        lines = []
        for record in records[:LIST_LIMIT]:
            context = _record_context(record)
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
        categories=CATEGORIES,
        days=days,
        title=title,
        weekly=weekly,
    )


def _record_context(record: StoredRecord) -> str:
    fields = record.fields or {}
    if record.category == "projects":
        return (
            fields.get("Next Action")
            or fields.get("next_action")
            or fields.get("Notes")
            or fields.get("notes")
            or ""
        )
    if record.category == "people":
        return (
            fields.get("Context")
            or fields.get("context")
            or fields.get("Follow Ups")
            or fields.get("follow_ups")
            or ""
        )
    if record.category == "ideas":
        return fields.get("One Liner") or fields.get("one_liner") or fields.get("Notes") or fields.get("notes") or ""
    return fields.get("Notes") or fields.get("notes") or ""


def _status_value(record: StoredRecord) -> str:
    fields = record.fields or {}
    value = fields.get("Status") or fields.get("status") or ""
    return str(value).strip().lower()


def _priority_value(record: StoredRecord) -> int:
    fields = record.fields or {}
    raw = fields.get("Priority") or fields.get("priority") or ""
    try:
        value = int(str(raw).strip())
    except ValueError:
        return 3
    if value < 1 or value > 5:
        return 3
    return value


def _status_priority(status: str) -> int:
    if status in {"blocked", "in progress", "active"}:
        return 0
    if status in {"open", "doing", "next", "todo"}:
        return 1
    if status in {"backlog", "someday", "later"}:
        return 2
    if status in COMPLETED_STATUSES:
        return 9
    return 3


def _filter_open_records(records: list[StoredRecord]) -> list[StoredRecord]:
    filtered = []
    for record in records:
        status = _status_value(record)
        if status and status in COMPLETED_STATUSES:
            continue
        filtered.append(record)
    return filtered


def _select_daily_records(storage, days: int) -> list[StoredRecord]:
    recent = storage.list_records(categories=CATEGORIES, days=days)
    if recent:
        recent.sort(key=lambda r: (_priority_value(r), r.created_at))
        return recent
    all_records = storage.list_records(categories=CATEGORIES, days=None)
    open_records = _filter_open_records(all_records)
    open_records.sort(
        key=lambda r: (_priority_value(r), _status_priority(_status_value(r)), r.created_at)
    )
    return open_records[:LIST_LIMIT]


def _send_digest_list(room_id: str, person_id: str, days: int, title: str) -> None:
    config = load_config()
    storage = build_adapter(config.storage.class_path, config.storage.settings)
    if days == 1:
        records = _select_daily_records(storage, days=days)
    else:
        records = storage.list_records(categories=CATEGORIES, days=days)
        records.sort(key=lambda r: (_priority_value(r), r.created_at))
    lines = [title]
    items = []
    for idx, record in enumerate(records[:LIST_LIMIT], start=1):
        context = _record_context(record)
        line = f"{idx}) {record.category}: {record.title}"
        if context:
            line += f" — {context}"
        lines.append(line)
        items.append(
            {
                "record_id": record.record_id,
                "category": record.category,
                "title": record.title,
                "fields": record.fields or {},
            }
        )
    if not items:
        lines.append("No items found.")
    message = "\n".join(lines)
    token = os.environ.get("WEBEX_BOT_TOKEN")
    if token:
        _webex_post_message(room_id, token, message)
    state = _load_state()
    state = _prune_state(state)
    room_state = state.setdefault(room_id, {})
    room_state[person_id] = {
        "updated_at": datetime.now(timezone.utc).timestamp(),
        "last_list": items,
        "pending_update": None,
    }
    _save_state(state)


def _build_field_options(record: dict, property_map: dict | None) -> list[dict]:
    if property_map:
        options = []
        for key, meta in property_map.items():
            options.append({"key": key, "name": meta.get("name", key)})
        return options
    fields = record.get("fields", {})
    return [{"key": key, "name": key} for key in fields.keys()]


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

    room_id = message.get("roomId") or ""
    if not room_id:
        return {"statusCode": 200, "body": "missing room id"}
    text = (message.get("text") or "").strip()
    if not text:
        return {"statusCode": 200, "body": "empty message"}
    if text.startswith(("[SB DIGEST]", "Filed as", "Needs review", "Daily Digest", "Weekly Review")):
        return {"statusCode": 200, "body": "ignored system message"}

    if _strip_bot_prefix(text).strip().lower() in {"cancel", "update cancel"}:
        state = _load_state()
        room_state = state.get(room_id, {})
        person_id = message.get("personId", "")
        if person_id in room_state:
            room_state[person_id]["pending_update"] = None
            room_state[person_id]["updated_at"] = datetime.now(timezone.utc).timestamp()
            _save_state(state)
        _webex_post_message(room_id, token, "Update canceled.")
        return {"statusCode": 200, "body": "update canceled"}

    state = _load_state()
    state = _prune_state(state)
    room_state = state.get(room_id, {})
    person_state = room_state.get(message.get("personId", ""), {})
    pending = person_state.get("pending_update")
    if pending and pending.get("awaiting_value"):
        field_key = pending.get("field_key")
        field_name = pending.get("field_name", field_key)
        if field_key:
            record_id = pending["record_id"]
            category = pending["category"]
            config = load_config()
            storage = build_adapter(config.storage.class_path, config.storage.settings)
            record = storage.update_record(category, record_id, {field_key: text})
            person_state["pending_update"] = None
            person_state["updated_at"] = datetime.now(timezone.utc).timestamp()
            room_state[message.get("personId", "")] = person_state
            state[room_id] = room_state
            _save_state(state)
            _webex_post_message(room_id, token, f"Updated {record.title} — {field_name} set to '{text}'.")
            return {"statusCode": 200, "body": "updated"}

    if pending:
        selection, value = _parse_field_selection(text)
        if selection is None:
            _webex_post_message(room_id, token, "Reply with a field number (e.g., `2`) or `2 New Value`.")
            return {"statusCode": 200, "body": "awaiting field selection"}
        fields = pending.get("fields", [])
        if selection < 1 or selection > len(fields):
            _webex_post_message(room_id, token, "That number is out of range. Try again.")
            return {"statusCode": 200, "body": "field selection out of range"}
        field = fields[selection - 1]
        if value is None:
            person_state["pending_update"]["field_key"] = field["key"]
            person_state["pending_update"]["field_name"] = field["name"]
            person_state["pending_update"]["awaiting_value"] = True
            person_state["updated_at"] = datetime.now(timezone.utc).timestamp()
            room_state[message.get("personId", "")] = person_state
            state[room_id] = room_state
            _save_state(state)
            _webex_post_message(room_id, token, f"Send the new value for {field['name']}.")
            return {"statusCode": 200, "body": "awaiting update value"}
        record_id = pending["record_id"]
        category = pending["category"]
        update_key = field["key"]
        config = load_config()
        storage = build_adapter(config.storage.class_path, config.storage.settings)
        record = storage.update_record(category, record_id, {update_key: value})
        person_state["pending_update"] = None
        person_state["updated_at"] = datetime.now(timezone.utc).timestamp()
        room_state[message.get("personId", "")] = person_state
        state[room_id] = room_state
        _save_state(state)
        _webex_post_message(room_id, token, f"Updated {record.title} — {field['name']} set to '{value}'.")
        return {"statusCode": 200, "body": "updated"}

    update_request = _parse_update_request(text)
    if update_request is not None:
        last_list = person_state.get("last_list", [])
        if not last_list:
            _webex_post_message(room_id, token, "No recent list found. Send `next`, `today`, or `week` first.")
            return {"statusCode": 200, "body": "missing list"}
        if update_request < 1 or update_request > len(last_list):
            _webex_post_message(room_id, token, "That number is out of range. Try again.")
            return {"statusCode": 200, "body": "update selection out of range"}
        selected = last_list[update_request - 1]
        config = load_config()
        property_map = config.storage.settings.get("property_map", {}).get(selected["category"])
        options = _build_field_options(selected, property_map)
        lines = [f"Choose a field to update for {selected['title']}:"]
        for idx, option in enumerate(options, start=1):
            current = (selected.get("fields") or {}).get(option["name"], "")
            if current:
                lines.append(f"{idx}) {option['name']}: {current}")
            else:
                lines.append(f"{idx}) {option['name']}")
        room_state[message.get("personId", "")] = {
            "updated_at": datetime.now(timezone.utc).timestamp(),
            "last_list": last_list,
            "pending_update": {
                "record_id": selected["record_id"],
                "category": selected["category"],
                "fields": options,
                "awaiting_value": False,
            },
        }
        state[room_id] = room_state
        _save_state(state)
        _webex_post_message(room_id, token, "\n".join(lines))
        return {"statusCode": 200, "body": "update prompt sent"}

    command = _parse_command(text)
    if command:
        if command == "help":
            _webex_post_message(
                room_id,
                token,
                "[SB HELP]  \nCommands: next | today | week | help  \nUpdate: update <number>  \nPrefixes: person:, project:, idea:, admin:  \nFix replies: fix: person|project|idea|admin  \nCancel update: cancel",
            )
            return {"statusCode": 200, "body": "help sent"}
        if command == "week":
            _send_digest_list(room_id, message.get("personId", ""), days=7, title="[SB DIGEST] This Week")
            return {"statusCode": 200, "body": "weekly digest sent"}
        if command == "today":
            _send_digest_list(room_id, message.get("personId", ""), days=1, title="[SB DIGEST] Today")
            return {"statusCode": 200, "body": "daily digest sent"}
        _send_digest_list(room_id, message.get("personId", ""), days=14, title="[SB DIGEST] Next Focus")
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
