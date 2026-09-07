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


def get_appdata_manager() -> AppDataManager:
    global _appdata_manager
    if _appdata_manager is None:
        manager = AppDataManager(APPDATA_PATH)
        manager.load()
        _appdata_manager = manager
    return _appdata_manager