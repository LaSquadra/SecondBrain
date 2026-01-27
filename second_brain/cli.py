import argparse
import json
import os
from datetime import datetime

from second_brain.config import load_config
from second_brain.core.pipeline import Pipeline, build_digest
from second_brain.registry import build_adapter


def _ensure_data_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _load_adapters(config):
    capture = build_adapter(config.capture.class_path, config.capture.settings)
    ai = build_adapter(config.ai.class_path, config.ai.settings)
    storage = build_adapter(config.storage.class_path, config.storage.settings)
    notifier = build_adapter(config.notifier.class_path, config.notifier.settings)
    return capture, ai, storage, notifier


def _parse_update_fields(set_pairs: list[str], json_payload: str | None) -> dict:
    updates: dict = {}
    if json_payload:
        try:
            payload = json.loads(json_payload)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON for --json: {exc}") from exc
        if not isinstance(payload, dict):
            raise SystemExit("--json must be a JSON object.")
        updates.update(payload)
    for pair in set_pairs or []:
        if "=" not in pair:
            raise SystemExit(f"Invalid --set value '{pair}'. Use key=value.")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"Invalid --set value '{pair}'. Use key=value.")
        updates[key] = value
    return updates


def _resolve_record_id(storage, category: str, name: str) -> str:
    if hasattr(storage, "find_record_by_title"):
        record_id = storage.find_record_by_title(category, name)
        if record_id:
            return record_id
        raise SystemExit(f"No record found in {category} with title '{name}'.")
    records = storage.list_records([category])
    matches = [record for record in records if record.title == name]
    if not matches:
        raise SystemExit(f"No record found in {category} with title '{name}'.")
    if len(matches) > 1:
        ids = [record.record_id for record in matches]
        raise SystemExit(f"Multiple records match '{name}' in {category}: {ids}")
    return matches[0].record_id


def cmd_capture(args) -> None:
    config = load_config(args.config)
    _ensure_data_dir(config.data_dir)
    capture = build_adapter(config.capture.class_path, config.capture.settings)
    if not hasattr(capture, "enqueue"):
        raise SystemExit("Capture adapter does not support enqueue().")
    capture.enqueue(args.text, source="cli", created_at=datetime.utcnow())
    print("Captured.")


def cmd_run(args) -> None:
    config = load_config(args.config)
    _ensure_data_dir(config.data_dir)
    capture, ai, storage, notifier = _load_adapters(config)
    pipeline = Pipeline(
        capture=capture,
        ai=ai,
        storage=storage,
        notifier=notifier,
        confidence_threshold=config.confidence_threshold,
    )
    stored = pipeline.run()
    print(f"Processed {len(stored)} items.")


def cmd_daily(args) -> None:
    config = load_config(args.config)
    _ensure_data_dir(config.data_dir)
    _, ai, storage, notifier = _load_adapters(config)
    build_digest(
        ai=ai,
        storage=storage,
        notifier=notifier,
        categories=["projects", "people", "ideas", "admin"],
        days=1,
        title="Daily Digest",
        weekly=False,
    )


def cmd_weekly(args) -> None:
    config = load_config(args.config)
    _ensure_data_dir(config.data_dir)
    _, ai, storage, notifier = _load_adapters(config)
    build_digest(
        ai=ai,
        storage=storage,
        notifier=notifier,
        categories=["projects", "people", "ideas", "admin"],
        days=7,
        title="Weekly Review",
        weekly=True,
    )


def cmd_update(args) -> None:
    config = load_config(args.config)
    _ensure_data_dir(config.data_dir)
    storage = build_adapter(config.storage.class_path, config.storage.settings)
    updates = _parse_update_fields(args.set, args.json)
    if not updates:
        raise SystemExit("Provide updates via --set or --json.")
    record_id = args.record_id
    if not record_id:
        record_id = _resolve_record_id(storage, args.category, args.name)
    record = storage.update_record(args.category, record_id, updates)
    print(f"Updated {args.category} {record.record_id} ({record.title}).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Second Brain pipeline")
    parser.add_argument("--config", help="Path to config.json")
    sub = parser.add_subparsers(dest="command", required=True)

    capture_cmd = sub.add_parser("capture", help="Capture a thought into the queue")
    capture_cmd.add_argument("text", help="Thought text")
    capture_cmd.set_defaults(func=cmd_capture)

    run_cmd = sub.add_parser("run", help="Process queued items")
    run_cmd.set_defaults(func=cmd_run)

    daily_cmd = sub.add_parser("daily", help="Send daily digest")
    daily_cmd.set_defaults(func=cmd_daily)

    weekly_cmd = sub.add_parser("weekly", help="Send weekly review")
    weekly_cmd.set_defaults(func=cmd_weekly)

    update_cmd = sub.add_parser("update", help="Update a record in storage")
    update_cmd.add_argument(
        "category",
        choices=["people", "projects", "ideas", "admin"],
        help="Category of the record to update",
    )
    id_group = update_cmd.add_mutually_exclusive_group(required=True)
    id_group.add_argument("--id", dest="record_id", help="Storage record id")
    id_group.add_argument("--name", dest="name", help="Record title to match")
    update_cmd.add_argument(
        "--set",
        action="append",
        default=[],
        help="Field update as key=value (repeatable)",
    )
    update_cmd.add_argument(
        "--json",
        dest="json",
        help="JSON object of field updates",
    )
    update_cmd.set_defaults(func=cmd_update)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
