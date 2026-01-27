from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List
from uuid import uuid4

from second_brain.core.interfaces import CaptureAdapter
from second_brain.core.models import CaptureItem


class QueueCapture(CaptureAdapter):
    def __init__(self, queue_path: str = "data/inbox_queue.json") -> None:
        self.queue_path = queue_path

    def enqueue(self, text: str, source: str, created_at: datetime) -> None:
        payload = {
            "id": str(uuid4()),
            "text": text,
            "source": source,
            "created_at": created_at.isoformat(),
        }
        items = self._read_queue()
        items.append(payload)
        self._write_queue(items)

    def fetch(self) -> List[CaptureItem]:
        items = self._read_queue()
        self._write_queue([])
        capture_items = []
        for item in items:
            capture_items.append(
                CaptureItem(
                    item_id=item["id"],
                    text=item["text"],
                    source=item.get("source", "queue"),
                    created_at=datetime.fromisoformat(item["created_at"]),
                    raw=item,
                )
            )
        return capture_items

    def _read_queue(self) -> List[dict]:
        if not os.path.exists(self.queue_path):
            return []
        with open(self.queue_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_queue(self, items: List[dict]) -> None:
        dir_name = os.path.dirname(self.queue_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(self.queue_path, "w", encoding="utf-8") as handle:
            json.dump(items, handle, indent=2)
