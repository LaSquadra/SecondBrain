import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class AdapterConfig:
    class_path: str
    settings: Dict[str, Any]


@dataclass
class AppConfig:
    data_dir: str
    confidence_threshold: float
    capture: AdapterConfig
    ai: AdapterConfig
    storage: AdapterConfig
    notifier: AdapterConfig


DEFAULT_CONFIG_PATH = "config.json"
ENV_CONFIG_PATH = "SB_CONFIG_PATH"


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


def _resolve_env(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        env_key = value[1:]
        return os.environ.get(env_key, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def load_config(path: Optional[str] = None) -> AppConfig:
    load_dotenv()
    config_path = path or os.environ.get(ENV_CONFIG_PATH, DEFAULT_CONFIG_PATH)
    if not path and config_path == DEFAULT_CONFIG_PATH and not os.path.exists(config_path):
        example_path = "config.example.json"
        if os.path.exists(example_path):
            config_path = example_path
    with open(config_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    raw = _resolve_env(raw)

    def _adapter(key: str) -> AdapterConfig:
        payload = raw.get(key, {})
        return AdapterConfig(
            class_path=payload.get("class", ""),
            settings=payload.get("settings", {}),
        )

    return AppConfig(
        data_dir=raw.get("data_dir", "data"),
        confidence_threshold=float(raw.get("confidence_threshold", 0.6)),
        capture=_adapter("capture"),
        ai=_adapter("ai"),
        storage=_adapter("storage"),
        notifier=_adapter("notifier"),
    )
