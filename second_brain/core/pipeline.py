from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

from second_brain.core.interfaces import AIProvider, CaptureAdapter, Notifier, StorageAdapter
from second_brain.core.models import CaptureItem, ClassificationResult, StoredRecord


VALID_CATEGORIES = {"people", "projects", "ideas", "admin"}


class Pipeline:
    def __init__(
        self,
        capture: CaptureAdapter,
        ai: AIProvider,
        storage: StorageAdapter,
        notifier: Notifier,
        confidence_threshold: float,
    ) -> None:
        self.capture = capture
        self.ai = ai
        self.storage = storage
        self.notifier = notifier
        self.confidence_threshold = confidence_threshold

    def run(self) -> List[StoredRecord]:
        items = self.capture.fetch()
        stored: List[StoredRecord] = []
        for item in items:
            result = self.ai.classify(item.text)
            stored_record = self._handle_classification(item, result)
            if stored_record:
                stored.append(stored_record)
        return stored

    def _handle_classification(
        self, item: CaptureItem, result: ClassificationResult
    ) -> Optional[StoredRecord]:
        category = result.category
        if category not in VALID_CATEGORIES:
            category = "admin"
            result = ClassificationResult(
                category=category,
                confidence=min(result.confidence, 0.4),
                title=result.title,
                fields=result.fields,
                raw=result.raw,
            )

        log_entry = {
            "source_id": item.item_id,
            "source": item.source,
            "captured_text": item.text,
            "category": category,
            "title": result.title,
            "confidence": result.confidence,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if result.confidence < self.confidence_threshold:
            log_entry["status"] = "needs_review"
            self.storage.log_inbox(log_entry)
            self.notifier.notify_needs_review(
                f"Needs review: '{result.title}' ({category}, {result.confidence:.2f})."
            )
            return None

        record_fields = dict(result.fields)
        if "name" not in record_fields and "title" not in record_fields:
            record_fields["name"] = result.title
        if category == "people":
            record_fields["last_touched"] = datetime.utcnow().date().isoformat()
        if category == "admin":
            due_date = record_fields.get("due_date", "")
            if not _is_reasonable_due_date(due_date):
                record_fields["due_date"] = ""
        stored_record = self.storage.store(category, record_fields)
        log_entry["status"] = "filed"
        log_entry["record_id"] = stored_record.record_id
        self.storage.log_inbox(log_entry)
        self.notifier.notify_filed(
            f"Filed as {category}: {stored_record.title} ({result.confidence:.2f})."
        )
        return stored_record


def build_digest(
    ai: AIProvider,
    storage: StorageAdapter,
    notifier: Notifier,
    categories: Iterable[str],
    days: int,
    title: str,
    weekly: bool = False,
) -> None:
    records = storage.list_records(categories=categories, days=days)
    if weekly:
        summary = ai.summarize_weekly(records)
    else:
        summary = ai.summarize_daily(records)
    notifier.notify_digest(f"{title}\n{summary.body}")


def _is_valid_date(value: str) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _is_reasonable_due_date(value: str) -> bool:
    if not _is_valid_date(value):
        return False
    try:
        due = datetime.fromisoformat(value).date()
    except ValueError:
        return False
    return due >= datetime.utcnow().date()
