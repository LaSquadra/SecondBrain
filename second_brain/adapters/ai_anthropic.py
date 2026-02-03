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


class AnthropicProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20240620",
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
        payload = self._chat(CLASSIFICATION_PROMPT, text)
        content = payload.get("content", [{}])[0].get("text", "{}").strip()
        data = json.loads(content)
        return ClassificationResult(
            category=data.get("category", "admin"),
            confidence=float(data.get("confidence", 0.0)),
            title=data.get("title", "Untitled"),
            fields=data.get("fields", {}),
            raw=data,
        )

    def summarize_daily(self, records: Iterable[StoredRecord]) -> DigestSummary:
        body = self._summarize(records, DAILY_DIGEST_PROMPT)
        return DigestSummary(title="Daily Digest", body=body, word_count=len(body.split()))

    def summarize_weekly(self, records: Iterable[StoredRecord]) -> DigestSummary:
        body = self._summarize(records, WEEKLY_DIGEST_PROMPT)
        return DigestSummary(title="Weekly Review", body=body, word_count=len(body.split()))

    def _summarize(self, records: Iterable[StoredRecord], prompt: str) -> str:
        text = _records_to_text(records)
        payload = self._chat(prompt, text)
        return payload.get("content", [{}])[0].get("text", "").strip()

    def _chat(self, system_prompt: str, user_text: str) -> dict:
        url = "https://api.anthropic.com/v1/messages"
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 512,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_text}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("x-api-key", self.api_key)
        request.add_header("anthropic-version", "2023-06-01")
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
                raise RuntimeError(f"Anthropic HTTP {exc.code}: {body}") from exc


def _records_to_text(records: Iterable[StoredRecord]) -> str:
    lines = []
    for record in records:
        lines.append(f"{record.category}: {record.title} :: {record.fields}")
    return "\n".join(lines) or "No recent items."
