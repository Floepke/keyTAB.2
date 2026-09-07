"""Complete keyTAB2 document layout editor."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, fields
from typing import Any

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFontComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from keytab2_model.events import GridBandEvent
from keytab2_model.font import Font
from keytab2_model.layout import LAYOUT_FLOAT_CONFIG, Layout


FIELD_GROUPS = {
    "Page": ("scale", "page_orientation", "read_direction", "page_width_mm", "page_height_mm", "page_top_margin_mm", "page_bottom_margin_mm", "page_left_margin_mm", "page_right_margin_mm", "header_height_mm", "footer_height_mm"),
    "Notes": ("black_note_rule", "note_stem_length_semitone", "note_stem_thickness_mm", "note_stopsign_thickness_mm", "note_continuation_dot_size_mm", "note_midinote_left_color", "note_midinote_right_color", "note_width_scaling", "notehead_height_scaling", "notehead_tilt", "beam_thickness_mm", "beam_corner_radius_mm", "grace_note_outline_width_mm", "grace_note_scale"),
    "Symbols": ("pedal_symbol_thickness_mm", "pedal_background_padding_mm", "text_background_padding_mm", "slur_width_sides_mm", "slur_width_middle_mm", "hairpin_line_width_mm", "hairpin_width_mm", "dynamic_symbol_font_size_pt", "dynamic_symbol_background_padding_mm", "dynamic_rotation", "countline_dash_pattern", "countline_thickness_mm"),
    "Grid": ("measure_grouping", "grid_band_track", "grid_barline_thickness_mm", "grid_gridline_thickness_mm", "grid_gridline_dash_pattern_mm", "grid_band_color", "grid_band_start_phase", "time_signature_indicator_type", "time_signature_indicator_lane_width_mm", "time_signature_indicator_guide_thickness_mm", "time_signature_indicator_divide_guide_thickness_mm", "measure_numbering_guide_thickness_mm", "measure_numbering_guide_dash_pattern_mm", "measure_numbering_placement"),
    "Stave": ("stave_two_line_thickness_mm", "stave_three_line_thickness_mm", "stave_clef_line_thickness_mm", "stave_ledger_line_length_mm", "stave_clef_line_dash_pattern_mm", "mini_piano_octave_numbering", "mini_piano_color"),
    "Fonts": ("time_signature_indicator_classic_font", "time_signature_indicator_klavarskribo_font", "measure_numbering_font", "font_text", "font_title", "font_composer", "font_copyright", "font_arranger", "font_lyricist"),
    "Visibility": tuple(field.name for field in fields(Layout) if field.name.endswith("_visible")),
}

CHOICES = {
    "page_orientation": ("portrait", "landscape"),
    "read_direction": ("vertical", "horizontal"),
    "black_note_rule": ("above_stem", "below_stem", "above_stem_if_collision", "above_stem_if_chord_and_white_note_same_hand"),
    "grid_band_start_phase": ("dark", "light"),
    "time_signature_indicator_type": ("classical", "klavarskribo", "classical & klavarskribo"),
    "measure_numbering_placement": ("system", "barline"),
}


def _label(field_name: str) -> str:
    return field_name.replace("_", " ").replace("mm", "mm").title()


class FontEditor(QWidget):
    """Compact editor for a persisted keyTAB2 Font dataclass."""

    def __init__(self, font: Font, parent=None) -> None:
        super().__init__(parent)
        self.family = QFontComboBox(self)
        self.family.setCurrentFont(QFont(font.family))
        self.size = QDoubleSpinBox(self)
        self.size.setRange(4.0, 200.0)
        self.size.setDecimals(1)
        self.size.setValue(font.size_pt)
        self.bold = QCheckBox("B", self)
        self.bold.setChecked(font.bold)
        self.italic = QCheckBox("I", self)
        self.italic.setChecked(font.italic)
        self.underline = QCheckBox("U", self)
        self.underline.setChecked(font.underline)
        self.x_offset = QDoubleSpinBox(self)
        self.y_offset = QDoubleSpinBox(self)
        for control, value in ((self.x_offset, font.x_offset), (self.y_offset, font.y_offset)):
            control.setRange(-100.0, 100.0)
            control.setDecimals(2)
            control.setValue(value)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.family, 2)
        layout.addWidget(self.size)
        layout.addWidget(self.bold)
        layout.addWidget(self.italic)
        layout.addWidget(self.underline)
        layout.addWidget(QLabel("X", self))
        layout.addWidget(self.x_offset)
        layout.addWidget(QLabel("Y", self))
        layout.addWidget(self.y_offset)

    def value(self) -> Font:
        return Font(self.family.currentFont().family() or "Edwin", self.size.value(), self.bold.isChecked(), self.italic.isChecked(), self.underline.isChecked(), self.x_offset.value(), self.y_offset.value())


class ColorEditor(QWidget):
    def __init__(self, color: str, parent=None) -> None:
        super().__init__(parent)
        self._edit = QLineEdit(color, self)
        self._button = QPushButton("Color", self)
        self._button.clicked.connect(self._pick_color)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._edit, 1)
        layout.addWidget(self._button)

    def value(self) -> str:
        return self._edit.text().strip() or "#ccc"

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.value()), self, "Select Color")
        if color.isValid():
            self._edit.setText(color.name())


class StyleDialog(QDialog):
    """Edit every persisted Layout field using typed controls."""

    def __init__(self, layout: Layout, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Style")
        self.resize(880, 650)
        self._editors: dict[str, QWidget] = {}
        self._layout = deepcopy(layout)
        tabs = QTabWidget(self)
        for title, names in FIELD_GROUPS.items():
            tabs.addTab(self._tab(names), title)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addWidget(tabs, 1)
        root.addWidget(buttons)

    def value(self) -> Layout:
        values: dict[str, Any] = {}
        for field in fields(Layout):
            editor = self._editors[field.name]
            if isinstance(editor, QCheckBox):
                values[field.name] = editor.isChecked()
            elif isinstance(editor, QComboBox):
                values[field.name] = editor.currentText()
            elif isinstance(editor, (QDoubleSpinBox, QSpinBox)):
                values[field.name] = editor.value()
            elif isinstance(editor, FontEditor):
                values[field.name] = editor.value()
            elif isinstance(editor, ColorEditor):
                values[field.name] = editor.value()
            elif field.name == "grid_band_track":
                raw = json.loads(editor.text() or "[]")
                values[field.name] = [
                    GridBandEvent(
                        id=str(item.get("id", "")) or GridBandEvent().id,
                        start_tick=int(item.get("start_tick", 0)),
                        duration_ticks=int(item.get("duration_ticks", 256)),
                    )
                    for item in raw
                ]
            elif field.name.endswith("_dash_pattern_mm") or field.name == "countline_dash_pattern":
                values[field.name] = [float(value) for value in editor.text().split(",") if value.strip()]
            else:
                values[field.name] = editor.text()
        return Layout(**values)

    def _tab(self, names: tuple[str, ...]) -> QScrollArea:
        content = QWidget(self)
        form = QFormLayout(content)
        for name in names:
            editor = self._editor_for(name, getattr(self._layout, name))
            self._editors[name] = editor
            form.addRow(_label(name) + ":", editor)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    def _editor_for(self, name: str, value: Any) -> QWidget:
        if isinstance(value, bool):
            editor = QCheckBox(self)
            editor.setChecked(value)
            return editor
        if name in CHOICES:
            editor = QComboBox(self)
            editor.addItems(CHOICES[name])
            editor.setCurrentText(value)
            return editor
        if isinstance(value, Font):
            return FontEditor(value, self)
        if name.endswith("_color"):
            return ColorEditor(value, self)
        if name == "grid_band_track":
            data = [
                {"id": event.id, "start_tick": event.start_tick, "duration_ticks": event.duration_ticks}
                for event in value
            ]
            editor = QLineEdit(json.dumps(data, separators=(",", ":")), self)
            editor.setPlaceholderText("[]")
            return editor
        if isinstance(value, list):
            return QLineEdit(", ".join(str(item) for item in value), self)
        if isinstance(value, (float, int)):
            limits = LAYOUT_FLOAT_CONFIG.get(name, {"min": -1000.0, "max": 10000.0, "step": 0.05})
            editor = QDoubleSpinBox(self)
            editor.setRange(limits["min"], limits["max"])
            editor.setSingleStep(limits["step"])
            editor.setDecimals(2)
            editor.setValue(value)
            return editor
        return QLineEdit(str(value), self)