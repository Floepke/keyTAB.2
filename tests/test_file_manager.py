from __future__ import annotations

import tempfile
import struct
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from file_manager import FileManager
from keytab2_model import KeyTab2Document, NoteEvent, TempoEvent, TextEvent
from midi_importer import load_midi


class FileManagerTests(unittest.TestCase):
    def test_clear_recent_paths_removes_persisted_paths(self) -> None:
        app_data = Mock()

        with patch("file_manager.get_appdata_manager", return_value=app_data):
            FileManager().clear_recent_paths()

        app_data.set.assert_called_once_with("recent_files", [])
        app_data.save.assert_called_once_with()

    def test_opened_documents_are_added_to_recent_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.keytab2"
            second_path = Path(directory) / "second.keytab2"
            KeyTab2Document.new().save(first_path)
            KeyTab2Document.new().save(second_path)
            app_data = Mock()
            app_data.get.return_value = [str(first_path), str(second_path)]

            with patch("file_manager.get_appdata_manager", return_value=app_data):
                manager = FileManager()
                self.assertTrue(manager.open_path(second_path))
                app_data.get.return_value = [str(second_path), str(first_path)]
                self.assertEqual(manager.recent_paths(), (second_path, first_path))

        app_data.set.assert_has_calls([
            call("last_file_dialog_dir", str(second_path.parent)),
            call("last_opened_file", str(second_path)),
            call("recent_files", [str(second_path), str(first_path)]),
        ])
        app_data.save.assert_called_once_with()

    def test_midi_import_uses_default_stave_range_and_six_measure_systems(self) -> None:
        track = b"\x00\xff\x58\x04\x04\x02\x18\x08" + b"\x00\x90\x3c\x40" + b"\xe9\x00\x80\x3c\x00" + b"\x00\xff\x2f\x00"
        midi = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(track)) + track
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.mid"
            path.write_bytes(midi)
            document = load_midi(path)

        systems = [system for page in document.pages for system in page.systems]
        self.assertEqual(document.pages[0].systems[0].staves[0].pitch_range, [36, 84])
        self.assertEqual(len(systems), 2)
        self.assertEqual((systems[0].start_tick, systems[0].end_tick), (0, 6144))
        self.assertEqual(systems[1].staves[0].events[0].pitch, 60)
    def test_saves_and_loads_the_page_oriented_document(self) -> None:
        manager = FileManager()
        manager.document.score_info.title = "File manager round trip"
        page = manager.document.pages[0]
        system = page.systems[0]
        system.staves[0].events.append(NoteEvent(time=256, duration=128, pitch=60))
        system.events.append(TextEvent(text="dolce", start_tick=256))
        manager.document.timeline_events.append(TempoEvent(start_tick=1024, tempo=96))

        with tempfile.TemporaryDirectory() as directory:
            requested_path = Path(directory) / "round-trip"
            self.assertTrue(manager.save_to_path(requested_path))
            saved_path = requested_path.with_suffix(".keytab2")
            self.assertTrue(saved_path.exists())

            restored_manager = FileManager()
            self.assertTrue(restored_manager.open_path(saved_path))

        restored = restored_manager.document
        self.assertEqual(restored.score_info.title, "File manager round trip")
        self.assertEqual(restored.pages[0].systems[0].staves[0].events[0].pitch, 60)
        self.assertEqual(restored.pages[0].systems[0].events[0].text, "dolce")
        self.assertEqual(restored.timeline_events[-1].tempo, 96)


if __name__ == "__main__":
    unittest.main()