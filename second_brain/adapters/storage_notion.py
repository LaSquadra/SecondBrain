from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from second_brain.core.interfaces import StorageAdapter
from second_brain.core.models import StoredRecord


class NotionStorage(StorageAdapter):
    """Writes records into Notion databases.

    Requires per-category database IDs and a property map.
    """

    def __init__(
        self,
        token: str,
        database_ids: dict,
        property_map: dict,
    ) -> None:
        self.token = token
        self.database_ids = database_ids
        self.property_map = property_map

    def store(self, category: str, record: dict) -> StoredRecord:
        database_id = self.database_ids.get(category)
        if not database_id:
            raise RuntimeError(f"Missing Notion database id for {category}.")
        properties = _build_properties(record, self.property_map.get(category, {}))
        payload = {"parent": {"database_id": database_id}, "properties": properties}
        response = self._request("https://api.notion.com/v1/pages", payload)
        title = record.get("name") or record.get("title") or "Untitled"
        created_at = datetime.utcnow()
        return StoredRecord(
            category=category,
            record_id=response.get("id", ""),
            title=title,
            fields=record,
            created_at=created_at,
        )

    def log_inbox(self, entry: dict) -> None:
        database_id = self.database_ids.get("inbox_log")
        if not database_id:
            raise RuntimeError("Missing Notion database id for inbox_log.")
        properties = _build_properties(entry, self.property_map.get("inbox_log", {}))
        payload = {"parent": {"database_id": database_id}, "properties": properties}
        self._request("https://api.notion.com/v1/pages", payload)

    def list_records(self, categories: Iterable[str], days: Optional[int] = None) -> List[StoredRecord]:
        results: List[StoredRecord] = []
        cutoff = None
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        for category in categories:
            database_id = self.database_ids.get(category)
            if not database_id:
                continue
            payload = {"page_size": 50}
            response = self._request(
                f"https://api.notion.com/v1/databases/{database_id}/query",
                payload,
            )
            for item in response.get("results", []):
                created = item.get("created_time")
                created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if cutoff and created_at < cutoff:
                    continue
                properties = item.get("properties", {})
                title = properties.get("Name", {}).get("title", [])
                title_text = title[0].get("plain_text") if title else "Untitled"
                fields = _extract_fields(properties)
                results.append(
                    StoredRecord(
                        category=category,
                        record_id=item.get("id", ""),
                        title=title_text,
                        fields=fields,
                        created_at=created_at,
                    )
                )
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results

    def find_record_by_title(self, category: str, title: str) -> str | None:
        database_id = self.database_ids.get(category)
        if not database_id:
            raise RuntimeError(f"Missing Notion database id for {category}.")
        title_prop = _get_title_property_name(self.property_map.get(category, {}))
        payload = {
            "page_size": 5,
            "filter": {
                "property": title_prop,
                "title": {"equals": title},
            },
        }
        response = self._request(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            payload,
        )
        results = response.get("results", [])
        if not results:
            return None
        if len(results) > 1:
            ids = [item.get("id", "") for item in results]
            raise RuntimeError(f"Multiple records match '{title}' in {category}: {ids}")
        return results[0].get("id", "")

    def update_record(self, category: str, record_id: str, fields: dict) -> StoredRecord:
        mapping = self.property_map.get(category, {})
        properties = _build_properties_partial(fields, mapping)
        if not properties:
            raise RuntimeError("No valid fields to update.")
        payload = {"properties": properties}
        response = self._request(
            f"https://api.notion.com/v1/pages/{record_id}",
            payload,
            method="PATCH",
        )
        created = response.get("created_time")
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00")) if created else datetime.utcnow()
        properties = response.get("properties", {})
        title_prop = _get_title_property_name(mapping)
        title_value = properties.get(title_prop, {}).get("title", [])
        title_text = title_value[0].get("plain_text") if title_value else "Untitled"
        return StoredRecord(
            category=category,
            record_id=response.get("id", record_id),
            title=title_text,
            fields=_extract_fields(properties),
            created_at=created_at,
        )

    def _request(self, url: str, payload: dict | None = None, method: str = "POST") -> dict:
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Notion-Version", "2022-06-28")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                if exc.fp is not None:
                    error_body = exc.fp.read().decode("utf-8")
            except Exception:
                error_body = "<failed to read error body>"
            print(
                "Notion HTTPError",
                {
                    "status": exc.code,
                    "reason": exc.reason,
                    "url": url,
                    "body": error_body,
                },
            )
            raise


def _build_properties(record: dict, mapping: dict) -> dict:
    properties = {}
    for field, prop in mapping.items():
        value = record.get(field, "")
        prop_type = prop.get("type", "rich_text")
        if prop_type == "title":
            content = "" if value is None else str(value)
            properties[prop["name"]] = {"title": [{"text": {"content": content}}]}
        elif prop_type == "rich_text":
            content = "" if value is None else str(value)
            properties[prop["name"]] = {"rich_text": [{"text": {"content": content}}]}
        elif prop_type == "select":
            if value in (None, ""):
                properties[prop["name"]] = {"select": None}
            else:
                properties[prop["name"]] = {"select": {"name": str(value)}}
        elif prop_type == "date":
            if value in (None, ""):
                properties[prop["name"]] = {"date": None}
            else:
                properties[prop["name"]] = {"date": {"start": str(value)}}
        else:
            properties[prop["name"]] = {"rich_text": [{"text": {"content": str(value)}}]}
    return properties


def _build_properties_partial(record: dict, mapping: dict) -> dict:
    properties = {}
    for field, value in record.items():
        prop = mapping.get(field)
        if not prop:
            raise RuntimeError(f"Unknown field '{field}' for Notion mapping.")
        prop_type = prop.get("type", "rich_text")
        if prop_type == "title":
            content = "" if value is None else str(value)
            properties[prop["name"]] = {"title": [{"text": {"content": content}}]}
        elif prop_type == "rich_text":
            content = "" if value is None else str(value)
            properties[prop["name"]] = {"rich_text": [{"text": {"content": content}}]}
        elif prop_type == "select":
            if value in (None, ""):
                properties[prop["name"]] = {"select": None}
            else:
                properties[prop["name"]] = {"select": {"name": str(value)}}
        elif prop_type == "date":
            if value in (None, ""):
                properties[prop["name"]] = {"date": None}
            else:
                properties[prop["name"]] = {"date": {"start": str(value)}}
        else:
            properties[prop["name"]] = {"rich_text": [{"text": {"content": str(value)}}]}
    return properties


def _get_title_property_name(mapping: dict) -> str:
    for _, prop in mapping.items():
        if prop.get("type") == "title":
            return prop.get("name", "Name")
    return "Name"


def _extract_fields(properties: dict) -> dict:
    fields = {}
    for name, prop in properties.items():
        prop_type = prop.get("type")
        if prop_type == "title":
            values = prop.get("title", [])
            fields[name] = " ".join(v.get("plain_text", "") for v in values).strip()
        elif prop_type == "rich_text":
            values = prop.get("rich_text", [])
            fields[name] = " ".join(v.get("plain_text", "") for v in values).strip()
        elif prop_type == "select":
            fields[name] = (prop.get("select") or {}).get("name", "")
        elif prop_type == "date":
            fields[name] = (prop.get("date") or {}).get("start", "")
        else:
            fields[name] = ""
    return fields
