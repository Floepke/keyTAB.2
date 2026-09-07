"""User-configurable settings for keyTAB2."""

from __future__ import annotations

from pathlib import Path

from persistence import TomlStore
from utils.CONSTANT import UTILS_SAVE_DIR


PREFERENCES_PATH = Path(UTILS_SAVE_DIR) / "preferences.toml"


class PreferencesManager(TomlStore):
    """Persist keyTAB2 user preferences in ~/.keyTAB2/preferences.toml."""


_preferences_manager: PreferencesManager | None = None


def get_preferences_manager() -> PreferencesManager:
    global _preferences_manager
    if _preferences_manager is None:
        manager = PreferencesManager(PREFERENCES_PATH)
        manager.register("timestamp_format", "%d-%m-%Y_%H:%M:%S")
        manager.load()
        _preferences_manager = manager
    return _preferences_manager