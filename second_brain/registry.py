import importlib
from typing import Any


def load_class(path: str) -> type:
    if not path or "." not in path:
        raise ValueError(f"Invalid class path: {path}")
    module_path, class_name = path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def build_adapter(path: str, settings: dict) -> Any:
    klass = load_class(path)
    return klass(**settings)
