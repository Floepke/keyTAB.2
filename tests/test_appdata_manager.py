from __future__ import annotations

from tempfile import TemporaryDirectory
import unittest
from pathlib import Path

from appdata_manager import AppDataManager, DEFAULT_THEME, THEMES


class AppDataManagerTests(unittest.TestCase):
    def test_theme_round_trips_and_invalid_values_fall_back_to_dark(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "appdata.toml"
            manager = AppDataManager(path)
            manager.load()
            manager.set("theme", "light")
            manager.save()

            restored = AppDataManager(path)
            restored.load()
            theme = str(restored.get("theme", DEFAULT_THEME))
            self.assertIn(theme, THEMES)
            self.assertEqual(theme, "light")


if __name__ == "__main__":
    unittest.main()