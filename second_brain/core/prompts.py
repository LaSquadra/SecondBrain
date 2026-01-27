CLASSIFICATION_PROMPT = """
You are a classifier for a personal second brain.
Return JSON only. No markdown. No explanation.

Schema:
{
  "category": "people|projects|ideas|admin",
  "confidence": 0.0,
  "title": "short human-friendly title",
  "fields": {
    "name": "...",
    "context": "...",
    "follow_ups": "...",
    "last_touched": "YYYY-MM-DD"
  }
}

Rules:
- Choose exactly one category.
- confidence is 0-1.
- If the input starts with a prefix like "person:", "project:", "idea:", or "admin:", use that category and set confidence to at least 0.8. Remove the prefix from the title/fields.
- For projects, include fields: name, status, next_action, notes.
- For ideas, include fields: name, one_liner, notes.
- For admin, include fields: name, status, due_date, notes.
- For people, include fields: name, context, follow_ups, last_touched.
- If ambiguous, still pick the best category but lower confidence.
""".strip()

DAILY_DIGEST_PROMPT = """
Summarize today's priorities in under 150 words. Include:
- Top 3 actions
- 1 stuck item
- 1 small win
Return plain text.
""".strip()

WEEKLY_DIGEST_PROMPT = """
Summarize this week in under 250 words. Include:
- What moved
- Biggest open loops
- 3 suggested actions for next week
- 1 recurring theme
Return plain text.
""".strip()
