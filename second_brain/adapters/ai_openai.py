from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Iterable, List, Optional

from second_brain.core.interfaces import AIProvider
from second_brain.core.models import ClassificationResult, DigestSummary, StoredRecord
from second_brain.core.prompts import CLASSIFICATION_PROMPT, DAILY_DIGEST_PROMPT, WEEKLY_DIGEST_PROMPT


class OpenAIProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        ca_bundle: Optional[str] = None,
        max_retries: int = 3,
        retry_backoff: float = 1.5,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.ca_bundle = ca_bundle or os.environ.get("SSL_CERT_FILE")
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    def classify(self, text: str) -> ClassificationResult:
        payload = self._chat([
            {"role": "system", "content": CLASSIFICATION_PROMPT},
            {"role": "user", "content": text},
        ])
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "{}").strip()
        data = json.loads(content)
        return ClassificationResult(
            category=data.get("category", "admin"),
            confidence=float(data.get("confidence", 0.0)),
            title=data.get("title", "Untitled"),
            fields=data.get("fields", {}),
            raw=data,
        )

    def summarize_daily(self, records: Iterable[StoredRecord]) -> DigestSummary:
        text = _records_to_text(records)
        payload = self._chat([
            {"role": "system", "content": DAILY_DIGEST_PROMPT},
            {"role": "user", "content": text},
        ])
        body = payload.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return DigestSummary(title="Daily Digest", body=body, word_count=len(body.split()))

    def summarize_weekly(self, records: Iterable[StoredRecord]) -> DigestSummary:
        text = _records_to_text(records)
        payload = self._chat([
            {"role": "system", "content": WEEKLY_DIGEST_PROMPT},
            {"role": "user", "content": text},
        ])
        body = payload.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return DigestSummary(title="Weekly Review", body=body, word_count=len(body.split()))

    def _chat(self, messages: List[dict]) -> dict:
        url = "https://api.openai.com/v1/chat/completions"
        body = json.dumps({"model": self.model, "messages": messages}).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Authorization", f"Bearer {self.api_key}")
        request.add_header("Content-Type", "application/json")
        context = None
        if self.ca_bundle and os.path.exists(self.ca_bundle):
            context = ssl.create_default_context(cafile=self.ca_bundle)
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, context=context, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < self.max_retries:
                    time.sleep(self.retry_backoff * (2**attempt))
                    continue
                body = exc.read().decode("utf-8") if exc.fp else ""
                raise RuntimeError(f"OpenAI HTTP {exc.code}: {body}") from exc


def _records_to_text(records: Iterable[StoredRecord]) -> str:
    lines = []
    for record in records:
        lines.append(f"{record.category}: {record.title} :: {record.fields}")
    return "\n".join(lines) or "No recent items."
