from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Iterable, List, Optional
from uuid import uuid4

from second_brain.core.interfaces import StorageAdapter
from second_brain.core.models import StoredRecord


class JsonStorage(StorageAdapter):
    def __init__(self, base_dir: str = "data") -> None:
        self.base_dir = base_dir

    def store(self, category: str, record: dict) -> StoredRecord:
        record_id = str(uuid4())
        created_at = datetime.utcnow()
        payload = {
            "id": record_id,
            "category": category,
            "title": record.get("name") or record.get("title") or "Untitled",
            "fields": record,
            "created_at": created_at.isoformat(),
        }
        items = self._read_table(category)
        items.append(payload)
        self._write_table(category, items)
        return StoredRecord(
            category=category,
            record_id=record_id,
            title=payload["title"],
            fields=record,
            created_at=created_at,
        )

    def log_inbox(self, entry: dict) -> None:
        items = self._read_table("inbox_log")
        items.append(entry)
        self._write_table("inbox_log", items)

    def list_records(self, categories: Iterable[str], days: Optional[int] = None) -> List[StoredRecord]:
        results: List[StoredRecord] = []
        cutoff = None
        if days is not None:
            cutoff = datetime.utcnow() - timedelta(days=days)
        for category in categories:
            items = self._read_table(category)
            for item in items:
                created_at = datetime.fromisoformat(item["created_at"])
                if cutoff and created_at < cutoff:
                    continue
                results.append(
                    StoredRecord(
                        category=item["category"],
                        record_id=item["id"],
                        title=item["title"],
                        fields=item.get("fields", {}),
                        created_at=created_at,
                    )
                )
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results

    def find_record_by_title(self, category: str, title: str) -> str | None:
        items = self._read_table(category)
        matches = [item for item in items if item.get("title") == title]
        if not matches:
            return None
        if len(matches) > 1:
            ids = [item.get("id") for item in matches]
            raise RuntimeError(f"Multiple records match '{title}' in {category}: {ids}")
        return matches[0].get("id")

    def update_record(self, category: str, record_id: str, fields: dict) -> StoredRecord:
        items = self._read_table(category)
        for item in items:
            if item.get("id") == record_id:
                stored_fields = item.get("fields", {})
                stored_fields.update(fields)
                item["fields"] = stored_fields
                if "name" in fields and fields["name"]:
                    item["title"] = str(fields["name"])
                elif "title" in fields and fields["title"]:
                    item["title"] = str(fields["title"])
                self._write_table(category, items)
                created_at = datetime.fromisoformat(item["created_at"])
                return StoredRecord(
                    category=item["category"],
                    record_id=item["id"],
                    title=item["title"],
                    fields=item.get("fields", {}),
                    created_at=created_at,
                )
        raise RuntimeError(f"Record id {record_id} not found in {category}.")

    def _read_table(self, name: str) -> List[dict]:
        path = self._table_path(name)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_table(self, name: str, items: List[dict]) -> None:
        os.makedirs(self.base_dir, exist_ok=True)
        path = self._table_path(name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(items, handle, indent=2)

    def _table_path(self, name: str) -> str:
        return os.path.join(self.base_dir, f"{name}.json")
