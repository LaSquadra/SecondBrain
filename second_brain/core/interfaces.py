from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, List, Optional

from second_brain.core.models import CaptureItem, ClassificationResult, DigestSummary, StoredRecord


class CaptureAdapter(ABC):
    @abstractmethod
    def fetch(self) -> List[CaptureItem]:
        raise NotImplementedError


class AIProvider(ABC):
    @abstractmethod
    def classify(self, text: str) -> ClassificationResult:
        raise NotImplementedError

    @abstractmethod
    def summarize_daily(self, records: Iterable[StoredRecord]) -> DigestSummary:
        raise NotImplementedError

    @abstractmethod
    def summarize_weekly(self, records: Iterable[StoredRecord]) -> DigestSummary:
        raise NotImplementedError


class StorageAdapter(ABC):
    @abstractmethod
    def store(self, category: str, record: dict) -> StoredRecord:
        raise NotImplementedError

    @abstractmethod
    def log_inbox(self, entry: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_records(self, categories: Iterable[str], days: Optional[int] = None) -> List[StoredRecord]:
        raise NotImplementedError

    @abstractmethod
    def update_record(self, category: str, record_id: str, fields: dict) -> StoredRecord:
        raise NotImplementedError


class Notifier(ABC):
    @abstractmethod
    def notify_filed(self, message: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def notify_needs_review(self, message: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def notify_digest(self, message: str) -> None:
        raise NotImplementedError
