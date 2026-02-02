#!/usr/bin/env python3
import json
import os
import re
import sys
import urllib.error
import urllib.request

from second_brain.config import load_dotenv


ENV_PATH = ".env"
PARENT_ENV = "NOTION_PARENT_PAGE_ID"
TARGET_ENV_KEYS = {
    "PEOPLE_DB",
    "PROJECTS_DB",
    "IDEAS_DB",
    "ADMIN_DB",
    "INBOX_LOG_DB",
    "COMPLETED_DB",
}


def _load_env_file(path: str) -> dict:
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key:
                values[key] = value
    return values


def _write_env_file(path: str, updates: dict) -> None:
    if not os.path.exists(path):
        raise RuntimeError("Missing .env file.")
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    updated = set()
    output = []
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            output.append(line)
            continue
        key, _ = raw.split("=", 1)
        key = key.strip()
        if key in updates:
            value = updates[key]
            if " " in value:
                value = f"\"{value}\""
            output.append(f"{key}={value}\n")
            updated.add(key)
        else:
            output.append(line)
    missing = [key for key in updates.keys() if key not in updated]
    for key in missing:
        value = updates[key]
        if " " in value:
            value = f"\"{value}\""
        output.append(f"{key}={value}\n")
    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(output)


def _normalize_page_id(value: str) -> str:
    value = value.strip()
    match = re.findall(r"[0-9a-fA-F]{32}", value.replace("-", ""))
    if match:
        return match[0]
    return value


def _request(token: str, url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Notion-Version", "2022-06-28")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8") if exc.fp else ""
        raise RuntimeError(f"Notion HTTP {exc.code}: {body_text}") from exc


def _db_payload(name: str, properties: dict, parent_id: str) -> dict:
    return {
        "parent": {"type": "page_id", "page_id": parent_id},
        "title": [{"type": "text", "text": {"content": name}}],
        "properties": properties,
    }


def main() -> int:
    if not os.path.exists(ENV_PATH):
        print("Missing .env. Copy .env.sample to .env and fill in values first.")
        return 1

    load_dotenv(ENV_PATH)
    env_file = _load_env_file(ENV_PATH)

    token = os.environ.get("NOTION_TOKEN", "").strip()
    parent_id = os.environ.get(PARENT_ENV, "").strip()
    if not token or not parent_id:
        print("NOTION_TOKEN and NOTION_PARENT_PAGE_ID are required in .env.")
        return 1

    existing = [key for key in TARGET_ENV_KEYS if env_file.get(key)]
    if existing:
        print(f".env already contains: {', '.join(sorted(existing))}. Aborting to avoid duplicates.")
        return 1

    parent_id = _normalize_page_id(parent_id)

    db_specs = [
        (
            "People",
            "PEOPLE_DB",
            {
                "Name": {"title": {}},
                "Context": {"rich_text": {}},
                "Follow Ups": {"rich_text": {}},
                "Last Touched": {"date": {}},
                "Status": {"select": {"options": []}},
                "Priority": {"select": {"options": []}},
            },
        ),
        (
            "Projects",
            "PROJECTS_DB",
            {
                "Name": {"title": {}},
                "Status": {"select": {"options": []}},
                "Next Action": {"rich_text": {}},
                "Notes": {"rich_text": {}},
                "Priority": {"select": {"options": []}},
            },
        ),
        (
            "Ideas",
            "IDEAS_DB",
            {
                "Name": {"title": {}},
                "One Liner": {"rich_text": {}},
                "Notes": {"rich_text": {}},
                "Status": {"select": {"options": []}},
                "Priority": {"select": {"options": []}},
            },
        ),
        (
            "Admin",
            "ADMIN_DB",
            {
                "Name": {"title": {}},
                "Status": {"select": {"options": []}},
                "Due Date": {"date": {}},
                "Notes": {"rich_text": {}},
                "Priority": {"select": {"options": []}},
            },
        ),
        (
            "Inbox Log",
            "INBOX_LOG_DB",
            {
                "Captured Text": {"rich_text": {}},
                "Category": {"select": {"options": []}},
                "Title": {"title": {}},
                "Confidence": {"rich_text": {}},
                "Status": {"select": {"options": []}},
            },
        ),
        (
            "Completed",
            "COMPLETED_DB",
            {
                "Name": {"title": {}},
                "Status": {"select": {"options": []}},
                "Next Action": {"rich_text": {}},
                "Notes": {"rich_text": {}},
                "Due Date": {"date": {}},
                "Completed Date": {"date": {}},
            },
        ),
    ]

    created = {}
    for name, env_key, props in db_specs:
        payload = _db_payload(name, props, parent_id)
        response = _request(token, "https://api.notion.com/v1/databases", payload)
        db_id = response.get("id", "").strip()
        if not db_id:
            print(f"Failed to create {name} database.")
            return 1
        created[env_key] = db_id
        print(f"Created {name}: {db_id}")

    _write_env_file(ENV_PATH, created)
    print("Updated .env with Notion database IDs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
