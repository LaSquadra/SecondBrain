from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import List, Optional

from second_brain.core.interfaces import CaptureAdapter
from second_brain.core.models import CaptureItem


class SlackCapture(CaptureAdapter):
    """Pulls messages from a Slack channel using the Web API.

    Requires a bot token with conversations:history and a channel ID.
    """

    def __init__(self, token: str, channel_id: str, cursor_path: str = "data/slack_cursor.json") -> None:
        self.token = token
        self.channel_id = channel_id
        self.cursor_path = cursor_path

    def fetch(self) -> List[CaptureItem]:
        latest = self._load_cursor()
        params = {
            "channel": self.channel_id,
            "limit": 100,
        }
        if latest:
            params["oldest"] = latest
        url = "https://slack.com/api/conversations.history"
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(f"{url}?{query}")
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Slack API error: {exc.code}") from exc

        if not payload.get("ok"):
            raise RuntimeError(f"Slack error: {payload.get('error', 'unknown')}")

        messages = payload.get("messages", [])
        items: List[CaptureItem] = []
        newest = latest
        for msg in messages:
            if msg.get("subtype"):
                continue
            ts = msg.get("ts")
            text = msg.get("text", "").strip()
            if not text:
                continue
            created_at = datetime.utcfromtimestamp(float(ts))
            items.append(
                CaptureItem(
                    item_id=ts,
                    text=text,
                    source="slack",
                    created_at=created_at,
                    raw=msg,
                )
            )
            if not newest or float(ts) > float(newest):
                newest = ts

        if newest:
            self._save_cursor(newest)
        return items

    def _load_cursor(self) -> Optional[str]:
        if not os.path.exists(self.cursor_path):
            return None
        with open(self.cursor_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload.get("latest")

    def _save_cursor(self, latest: str) -> None:
        dir_name = os.path.dirname(self.cursor_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(self.cursor_path, "w", encoding="utf-8") as handle:
            json.dump({"latest": latest}, handle, indent=2)
