"""Global Fusion palettes for the keyTAB2 application chrome."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory


THEMES = {
    "light": {
        "window": "#e7e9ed", "base": "#ffffff", "alternate": "#f3f5f7",
        "text": "#20252b", "button": "#f3f5f7", "highlight": "#1769aa",
        "highlighted_text": "#ffffff", "disabled": "#8a9099",
    },
    "dark": {
        "window": "#252a30", "base": "#1b1f24", "alternate": "#30363d",
        "text": "#e6edf3", "button": "#30363d", "highlight": "#4c9ed9",
        "highlighted_text": "#ffffff", "disabled": "#89929b",
    },
}


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply a complete Fusion palette to every Qt widget in the application."""
    if theme not in THEMES:
        raise ValueError(f"Unsupported theme: {theme}")
    fusion_style = next((style for style in QStyleFactory.keys() if style.lower() == "fusion"), "Fusion")
    app.setStyle(fusion_style)
    colors = THEMES[theme]
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["base"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["alternate"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors["base"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors["button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(colors["highlight"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["highlight"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["highlighted_text"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(colors["disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(colors["disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(colors["disabled"]))
    app.setPalette(palette)