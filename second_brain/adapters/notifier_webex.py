from __future__ import annotations

import json
import urllib.request

from second_brain.core.interfaces import Notifier


class WebexNotifier(Notifier):
    def __init__(self, token: str, room_id: str) -> None:
        self.token = token
        self.room_id = room_id

    def notify_filed(self, message: str) -> None:
        self._post(message)

    def notify_needs_review(self, message: str) -> None:
        self._post(message)

    def notify_digest(self, message: str) -> None:
        self._post(message)

    def _post(self, text: str) -> None:
        url = "https://webexapis.com/v1/messages"
        payload = json.dumps({"roomId": self.room_id, "text": text}).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=8) as response:
            response.read()
