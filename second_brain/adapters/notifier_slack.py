from __future__ import annotations

import json
import urllib.parse
import urllib.request

from second_brain.core.interfaces import Notifier


class SlackNotifier(Notifier):
    def __init__(self, token: str, channel_id: str) -> None:
        self.token = token
        self.channel_id = channel_id

    def notify_filed(self, message: str) -> None:
        self._post(message)

    def notify_needs_review(self, message: str) -> None:
        self._post(message)

    def notify_digest(self, message: str) -> None:
        self._post(message)

    def _post(self, text: str) -> None:
        url = "https://slack.com/api/chat.postMessage"
        payload = urllib.parse.urlencode({"channel": self.channel_id, "text": text}).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(f"Slack error: {data.get('error', 'unknown')}")
