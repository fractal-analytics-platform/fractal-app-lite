import json
from pathlib import Path
from typing import Any


def write_dict_to_file(path: str | Path, data: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_string_to_file(path: str | Path, data: str) -> None:
    Path(path).write_text(data, encoding="utf-8")
