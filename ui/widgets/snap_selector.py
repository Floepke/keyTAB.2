"""Dockable keyTAB-style rhythmic snap selector."""

from __future__ import annotations

from fractions import Fraction

from PySide6 import QtCore, QtGui, QtWidgets

from icons import get_qicon
from keytab2_model.document import TIME_PER_QUARTER
from utils.CONSTANT import SHORTEST_DURATION


LEFT_PANEL_PADDING_PX = 6
SNAP_DOCK_WIDTH_PX = 220
BASE_ITEMS: list[tuple[int, str]] = [
    (1, "Whole"), (2, "Half"), (4, "Quarter"), (8, "Eighth"),
    (16, "Sixteenth"), (32, "Thirty-second"),
    (64, "Sixty-fourth"), (128, "One hundred twenty-eighth"),
]


class SnapSizeSelector(QtWidgets.QWidget):
    """Select a base note length and equal divider for direct-paper input."""

    snapChanged = QtCore.Signal(int, int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(SNAP_DOCK_WIDTH_PX)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(LEFT_PANEL_PADDING_PX, 6, LEFT_PANEL_PADDING_PX, 6)
        layout.setSpacing(6)

        self.list = QtWidgets.QListWidget(self)
        self.list.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
        self.list.setMinimumWidth(SNAP_DOCK_WIDTH_PX - 2 * LEFT_PANEL_PADDING_PX)
        self.list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setToolTip("Select the base note length used to snap mouse input.")
        self.list.itemClicked.connect(self._on_list_item_clicked)
        self.list.itemSelectionChanged.connect(self._emit_changed)
        layout.addWidget(self.list)

        self._base = 8
        self._divide = 1
        self._populate_list()

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.minus_btn = QtWidgets.QToolButton(self)
        self.minus_btn.setIcon(get_qicon("minus", (36, 36)))
        self.minus_btn.setIconSize(QtCore.QSize(17, 17))
        self.minus_btn.setToolTip("Decrease the snap divider by one step.")
        self.minus_btn.clicked.connect(self._dec_divide)
        row.addWidget(self.minus_btn)

        self.label = QtWidgets.QLabel(self)
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Expanding)
        label_font = self.label.font()
        label_font.setPointSize(max(20, label_font.pointSize() * 2))
        self.label.setFont(label_font)
        self.label.setToolTip("Divider for equal snap subdivisions. Click to reset to one.")
        row.addWidget(self.label, 1)

        self.plus_btn = QtWidgets.QToolButton(self)
        self.plus_btn.setIcon(get_qicon("plus", (36, 36)))
        self.plus_btn.setIconSize(QtCore.QSize(17, 17))
        self.plus_btn.setToolTip("Increase the snap divider by one step.")
        self.plus_btn.clicked.connect(self._inc_divide)
        row.addWidget(self.plus_btn)
        layout.addLayout(row)

        self.list.installEventFilter(self)
        self.minus_btn.installEventFilter(self)
        self.plus_btn.installEventFilter(self)
        self.label.installEventFilter(self)
        self._update_ui()
        QtCore.QTimer.singleShot(0, self.adjust_to_fit)

    def refresh_icons(self, tint: str | None = None) -> None:
        self.minus_btn.setIcon(get_qicon("minus", (36, 36), tint))
        self.plus_btn.setIcon(get_qicon("plus", (36, 36), tint))

    def _populate_list(self) -> None:
        for base, name in BASE_ITEMS:
            item = QtWidgets.QListWidgetItem(f"{base} - {name}")
            item.setSizeHint(QtCore.QSize(item.sizeHint().width(), 28))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, base)
            self.list.addItem(item)
            if base == self._base:
                self.list.setCurrentItem(item)

    def _update_ui(self) -> None:
        if hasattr(self, "label"):
            self.label.setText(f"\N{DIVISION SIGN} {self._divide}")
        if hasattr(self, "minus_btn"):
            self.minus_btn.setEnabled(self._divide > 1)

    def adjust_to_fit(self) -> None:
        row_heights = sum(max(28, self.list.sizeHintForRow(index)) for index in range(self.list.count()))
        self.list.setFixedHeight(row_heights + self.list.frameWidth() * 2)
        self.setFixedHeight(row_heights + 72)

    def _emit_changed(self) -> None:
        selected = self.list.selectedItems()
        if selected:
            self._base = int(selected[0].data(QtCore.Qt.ItemDataRole.UserRole))
            self._divide = 1
            self._update_ui()
        self.snapChanged.emit(self._base, self._divide)

    def _on_list_item_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        self._base = int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        self._divide = 1
        self._update_ui()
        self.snapChanged.emit(self._base, self._divide)

    def _dec_divide(self) -> None:
        if self._divide > 1:
            self._divide -= 1
            self._update_ui()
            self.snapChanged.emit(self._base, self._divide)

    def _inc_divide(self) -> None:
        if self._divide < 64:
            self._divide += 1
            self._update_ui()
            self.snapChanged.emit(self._base, self._divide)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.Wheel and isinstance(event, QtGui.QWheelEvent):
            delta = event.angleDelta().y()
            if obj is self.list:
                row = max(0, self.list.currentRow())
                row = max(0, min(self.list.count() - 1, row + (-1 if delta > 0 else 1)))
                self.list.setCurrentRow(row)
                return True
            if obj in (self.minus_btn, self.plus_btn, self.label):
                if delta > 0:
                    self._inc_divide()
                elif delta < 0:
                    self._dec_divide()
                return True
        if event.type() == QtCore.QEvent.Type.MouseButtonPress and obj is self.label:
            if self._divide != 1:
                self._divide = 1
                self._update_ui()
                self.snapChanged.emit(self._base, self._divide)
            return True
        return super().eventFilter(obj, event)

    def get_snap_base(self) -> int:
        return self._base

    def get_snap_divide(self) -> int:
        return self._divide

    def get_snap_fraction(self) -> Fraction:
        return Fraction(1, self._base * self._divide)

    def get_snap_size(self) -> float:
        return max(float(SHORTEST_DURATION), TIME_PER_QUARTER * 4.0 / (self._base * self._divide))

    def set_snap(self, base: int, divide: int = 1, emit: bool = True) -> None:
        self._base = base if base in dict(BASE_ITEMS) else 8
        self._divide = max(1, min(64, int(divide)))
        self.list.blockSignals(True)
        self.list.setCurrentRow([item[0] for item in BASE_ITEMS].index(self._base))
        self.list.blockSignals(False)
        self._update_ui()
        if emit:
            self.snapChanged.emit(self._base, self._divide)


class SnapSizeDock(QtWidgets.QDockWidget):
    """Locked, dockable host for the snap selector."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("Snap Size", parent)
        self.setObjectName("SnapSizeDock")
        self.setMinimumWidth(SNAP_DOCK_WIDTH_PX)
        self.setFixedWidth(SNAP_DOCK_WIDTH_PX)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred)
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea | QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.selector = SnapSizeSelector(self)
        self.setWidget(self.selector)
        self.selector.snapChanged.connect(self._update_title)
        self._update_title()

    def _update_title(self, _base: int | None = None, _divide: int | None = None) -> None:
        fraction = self.selector.get_snap_fraction()
        self.setWindowTitle(f"Snap Size: {fraction.numerator}/{fraction.denominator} = {self.selector.get_snap_size():.1f}")