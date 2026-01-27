from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, List

from second_brain.core.models import ClassificationResult, DigestSummary, StoredRecord
from second_brain.core.interfaces import AIProvider


CATEGORY_KEYWORDS = {
    "people": ["meet", "met", "call", "coffee", "intro", "follow up", "connect"],
    "projects": ["project", "build", "launch", "ship", "deadline", "milestone"],
    "ideas": ["idea", "what if", "maybe", "concept", "hypothesis"],
    "admin": ["pay", "invoice", "renew", "schedule", "submit", "todo", "task"],
}


def _simple_title(text: str, max_words: int = 6) -> str:
    words = re.findall(r"\w+", text)
    return " ".join(words[:max_words]) if words else "Untitled"


def _best_category(text: str) -> tuple[str, float]:
    text_lower = text.lower()
    scores = {"people": 0, "projects": 0, "ideas": 0, "admin": 0}
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                scores[category] += 1
    best = max(scores, key=scores.get)
    score = scores[best]
    if score == 0:
        return "admin", 0.45
    confidence = min(0.5 + (score * 0.15), 0.9)
    return best, confidence


class RuleBasedAI(AIProvider):
    def classify(self, text: str) -> ClassificationResult:
        category, confidence = _best_category(text)
        title = _simple_title(text)
        now = datetime.utcnow().date().isoformat()
        fields = {}

        if category == "people":
            fields = {
                "name": title,
                "context": text,
                "follow_ups": "",
                "last_touched": now,
            }
        elif category == "projects":
            fields = {
                "name": title,
                "status": "active",
                "next_action": text,
                "notes": "",
            }
        elif category == "ideas":
            fields = {
                "name": title,
                "one_liner": text,
                "notes": "",
            }
        else:
            fields = {
                "name": title,
                "status": "open",
                "due_date": "",
                "notes": text,
            }

        return ClassificationResult(
            category=category,
            confidence=confidence,
            title=title,
            fields=fields,
            raw={"strategy": "rule_based"},
        )

    def summarize_daily(self, records: Iterable[StoredRecord]) -> DigestSummary:
        body = _summarize_records(list(records), max_items=5)
        return DigestSummary(title="Daily Digest", body=body, word_count=len(body.split()))

    def summarize_weekly(self, records: Iterable[StoredRecord]) -> DigestSummary:
        body = _summarize_records(list(records), max_items=8)
        return DigestSummary(title="Weekly Review", body=body, word_count=len(body.split()))


def _summarize_records(records: List[StoredRecord], max_items: int) -> str:
    if not records:
        return "No items filed recently."
    lines = []
    for record in records[:max_items]:
        lines.append(f"- {record.category}: {record.title}")
    return "\n".join(lines)
