from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class CaptureItem:
    item_id: str
    text: str
    source: str
    created_at: datetime
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClassificationResult:
    category: str
    confidence: float
    title: str
    fields: Dict[str, Any]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StoredRecord:
    category: str
    record_id: str
    title: str
    fields: Dict[str, Any]
    created_at: datetime


@dataclass
class DigestSummary:
    title: str
    body: str
    word_count: int
    meta: Optional[Dict[str, Any]] = None
