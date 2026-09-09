"""Application-managed state for keyTAB2."""

from __future__ import annotations

from pathlib import Path

from persistence import TomlStore
from utils.CONSTANT import UTILS_SAVE_DIR


APPDATA_PATH = Path(UTILS_SAVE_DIR) / "appdata.toml"


class AppDataManager(TomlStore):
    """Persist non-preference application state in ~/.keyTAB2/appdata.toml."""

    def __init__(self, path: Path = APPDATA_PATH) -> None:
        super().__init__(path, preserve_unknown=True)


_appdata_manager: AppDataManager | None = None
DEFAULT_THEME = "dark"
THEMES = {"light", "dark"}


def get_appdata_manager() -> AppDataManager:
    global _appdata_manager
    if _appdata_manager is None:
        manager = AppDataManager(APPDATA_PATH)
        manager.load()
        _appdata_manager = manager
    return _appdata_manager


def get_theme() -> str:
    """Return the persisted application theme, falling back to dark."""
    theme = str(get_appdata_manager().get("theme", DEFAULT_THEME))
    return theme if theme in THEMES else DEFAULT_THEME


def set_theme(theme: str) -> None:
    """Persist one of the supported application themes."""
    if theme not in THEMES:
        raise ValueError(f"Unsupported theme: {theme}")
    manager = get_appdata_manager()
    manager.set("theme", theme)
    manager.save()