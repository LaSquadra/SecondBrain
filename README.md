# Second Brain Tool (Modular Python)

This is a modular Python3 implementation of the second-brain loop described in `second_brain_outline.txt`.
It is designed to let you swap capture, AI, storage, and notification adapters (Slack vs Webex, Notion vs Airtable, etc.)
without changing core logic.

## Quick Start (Local, No APIs)

1. Copy `config.example.json` to `config.json`.
2. Ensure your `.env` contains `OPENAI_API_KEY=...` (loaded automatically).
3. Capture a thought:

```bash
python3 -m second_brain.cli capture "Follow up with Sam about the deck"
```

4. Process the queue:

```bash
python3 -m second_brain.cli run
```

5. Generate a digest:

```bash
python3 -m second_brain.cli daily
```

Local data is stored in `data/` as JSON.

## Adapter Overview

- Capture: `second_brain.adapters.capture_queue.QueueCapture` (default), `second_brain.adapters.capture_slack.SlackCapture`
- AI: `second_brain.adapters.ai_rules.RuleBasedAI` (default), `second_brain.adapters.ai_openai.OpenAIProvider`, `second_brain.adapters.ai_anthropic.AnthropicProvider`
- Storage: `second_brain.adapters.storage_json.JsonStorage` (default), `second_brain.adapters.storage_notion.NotionStorage`
- Notifier: `second_brain.adapters.notifier_console.ConsoleNotifier` (default), `second_brain.adapters.notifier_slack.SlackNotifier`, `second_brain.adapters.notifier_webex.WebexNotifier`

## Swapping Adapters

Update `config.json` with a different adapter class and settings. Example for Slack + Notion + OpenAI:

```json
{
  "data_dir": "data",
  "confidence_threshold": 0.6,
  "capture": {
    "class": "second_brain.adapters.capture_slack.SlackCapture",
    "settings": {
      "token": "$SLACK_TOKEN",
      "channel_id": "$SLACK_CHANNEL_ID",
      "cursor_path": "data/slack_cursor.json"
    }
  },
  "ai": {
    "class": "second_brain.adapters.ai_openai.OpenAIProvider",
    "settings": {
      "api_key": "$OPENAI_API_KEY",
      "model": "gpt-4o-mini",
      "ca_bundle": "$SSL_CERT_FILE"
    }
  },
  "storage": {
    "class": "second_brain.adapters.storage_notion.NotionStorage",
    "settings": {
      "token": "$NOTION_TOKEN",
      "database_ids": {
        "people": "...",
        "projects": "...",
        "ideas": "...",
        "admin": "...",
        "inbox_log": "..."
      },
      "property_map": {
        "people": {
          "name": {"name": "Name", "type": "title"},
          "context": {"name": "Context", "type": "rich_text"},
          "follow_ups": {"name": "Follow Ups", "type": "rich_text"},
          "last_touched": {"name": "Last Touched", "type": "date"}
        },
        "projects": {
          "name": {"name": "Name", "type": "title"},
          "status": {"name": "Status", "type": "select"},
          "next_action": {"name": "Next Action", "type": "rich_text"},
          "notes": {"name": "Notes", "type": "rich_text"}
        },
        "ideas": {
          "name": {"name": "Name", "type": "title"},
          "one_liner": {"name": "One Liner", "type": "rich_text"},
          "notes": {"name": "Notes", "type": "rich_text"}
        },
        "admin": {
          "name": {"name": "Name", "type": "title"},
          "status": {"name": "Status", "type": "select"},
          "due_date": {"name": "Due Date", "type": "date"},
          "notes": {"name": "Notes", "type": "rich_text"}
        },
        "inbox_log": {
          "captured_text": {"name": "Captured Text", "type": "rich_text"},
          "category": {"name": "Category", "type": "select"},
          "title": {"name": "Title", "type": "rich_text"},
          "confidence": {"name": "Confidence", "type": "rich_text"},
          "status": {"name": "Status", "type": "select"}
        }
      }
    }
  },
  "notifier": {
    "class": "second_brain.adapters.notifier_slack.SlackNotifier",
    "settings": {
      "token": "$SLACK_TOKEN",
      "channel_id": "$SLACK_CHANNEL_ID"
    }
  }
}
```

Environment variables can be referenced with a leading `$` in `config.json`. `.env` is loaded automatically.
If you hit SSL certificate errors, set `SSL_CERT_FILE` to a valid CA bundle path (and pass it via `ca_bundle`).
Rate-limit responses (HTTP 429) are retried with exponential backoff; you can tune `max_retries` and `retry_backoff`.

## Extending to Webex / Teams

Implement a new adapter that matches the interface in `second_brain/core/interfaces.py`:

- Capture: `fetch()` returns `CaptureItem` list
- Notifier: `notify_filed`, `notify_needs_review`, `notify_digest`

Then swap the class path in `config.json`.

## Webex Bot via AWS Lambda

This repo includes a Lambda handler that receives Webex webhook events, pulls the message text, and runs the pipeline.

### Setup

1. Create a Webex bot and note the bot access token.
2. Deploy `second_brain/lambda_handler.py` as your Lambda entry point (`second_brain.lambda_handler.handler`).
3. Create an API Gateway HTTP endpoint (POST) to your Lambda.
4. Create a Webex webhook pointing to the API Gateway URL with a secret.
5. Configure Lambda environment variables:

- `WEBEX_BOT_TOKEN`: Webex bot access token
- `WEBEX_WEBHOOK_SECRET`: Webhook secret for signature verification (optional but recommended)
- `WEBEX_BOT_EMAIL`: Bot email to ignore self-messages (optional)
- `SB_CONFIG_PATH`: Path to your config JSON in Lambda (optional)
- `SB_RUN_PIPELINE`: `true` to process immediately (default), `false` to only enqueue
- `SSL_CERT_FILE`: CA bundle path if needed

### Notes

- Lambda has a writable `/tmp` directory. If you use JSON storage or queue capture, point paths to `/tmp` in your config.
- See `config.lambda.example.json` for a `/tmp`-friendly sample config.
- The handler fetches the message text from the Webex API, then enqueues it and optionally runs the pipeline.
- Use `second_brain.adapters.notifier_webex.WebexNotifier` to send confirmations back to the same Webex space.

### Scheduling daily/weekly digests (EventBridge)

Create two EventBridge rules that invoke the same Lambda on a schedule with a JSON input:

Daily input:
```json
{ "digest": "daily" }
```

Weekly input:
```json
{ "digest": "weekly" }
```

Set Lambda env var `WEBEX_DIGEST_ROOM_ID` to the Webex space ID where digests should be posted.

## Notes

- Confidence threshold defaults to `0.6`. Lower confidence items go to the inbox log and trigger a review message.
- Use prefixes like `person:`, `project:`, `idea:`, or `admin:` to boost classification confidence.
- The OpenAI adapter is the default in the example config. Swap to the rule-based adapter for offline use.

## Fix workflow (Webex)

Reply in the same Webex thread with:

```
fix: idea
```

Supported categories: `person`, `project`, `idea`, `admin`. The system will re-file the original message using that category.

## Quick queries (Webex)

Send any of these as a message to the bot:

- `next` → Next Focus (last 14 days)
- `today` or `daily` → Today digest
- `week`, `this week`, or `weekly` → This Week digest
- `help` → list available commands
