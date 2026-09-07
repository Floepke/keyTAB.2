"""Small TOML-backed storage primitive used by keyTAB2 application state."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any


class TomlStore:
    """Persist registered, top-level values in a TOML file."""

    def __init__(self, path: Path, *, preserve_unknown: bool = False) -> None:
        self.path = path
        self.preserve_unknown = preserve_unknown
        self._defaults: dict[str, Any] = {}
        self._values: dict[str, Any] = {}

    def register(self, key: str, default: Any) -> None:
        self._defaults[key] = default
        self._values.setdefault(key, default)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value

    def remove(self, key: str) -> None:
        self._values.pop(key, None)

    def load(self) -> None:
        values: dict[str, Any] = {}
        try:
            with self.path.open("rb") as file:
                loaded = tomllib.load(file)
            if isinstance(loaded, dict):
                values = loaded
        except FileNotFoundError:
            pass
        except tomllib.TOMLDecodeError:
            pass

        if self.preserve_unknown:
            self._values = values
        else:
            self._values = {}
        for key, default in self._defaults.items():
            self._values[key] = values.get(key, default)
        self.save()

    def save(self) -> None:
        content = "# keyTAB2 application data\n\n" + "\n".join(
            f"{json.dumps(key)} = {self._toml_value(value)}"
            for key, value in self._values.items()
        )
        self._write_atomic(content + "\n")

    def _write_atomic(self, content: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.path)
        except Exception:
            os.unlink(temporary_path)
            raise

    def _toml_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return json.dumps(value)
        if isinstance(value, list):
            return "[" + ", ".join(self._toml_value(item) for item in value) + "]"
        if isinstance(value, dict):
            return "{ " + ", ".join(
                f"{json.dumps(str(key))} = {self._toml_value(item)}"
                for key, item in value.items()
            ) + " }"
        raise TypeError(f"{type(value).__name__} cannot be stored in TOML")