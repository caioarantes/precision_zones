# -*- coding: utf-8 -*-
"""Permanent hover-expand navigation sidebar for the Precision Zones dialog.

Adapted from the AGLgis sidebar with a neutral slate palette. Owns presentation
and navigation signals only; page switching stays in main_dialog.py.
"""
import os

from qgis.PyQt.QtCore import (
    QEasingCurve, QRectF, Qt, QSize, QPointF, QVariantAnimation, pyqtSignal
)
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from qgis.PyQt.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ..core.i18n import tr

SIDEBAR_COLLAPSED_WIDTH = 64
SIDEBAR_EXPANDED_WIDTH = 200
SIDEBAR_TOP = "#37474F"        # slate
SIDEBAR_BOTTOM = "#2A363C"
SIDEBAR_INDICATOR = "#90A4AE"
SIDEBAR_TEXT = "rgba(255, 255, 255, 218)"
SIDEBAR_MUTED = "rgba(255, 255, 255, 170)"

# (key, label) in stack/display order
PAGES = [
    ("resample", "Resampling"),
    ("pca", "PCA"),
    ("zones", "Zones"),
    ("filter", "Mode Filter"),
    ("analysis", "Analysis"),
]


class SidebarNavButton(QPushButton):
    """Navigation button with a compact rounded active indicator."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._indicator_color = QColor(SIDEBAR_INDICATOR)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._indicator_color)
        height = 28 if self.width() > 80 else 22
        y = (self.height() - height) / 2
        painter.drawRoundedRect(QRectF(0, y, 3.5, height), 1.75, 1.75)
        painter.end()


class Sidebar(QFrame):
    """Permanent left navigation; emits page_requested(key) on click."""

    page_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._active_page = PAGES[0][0]
        self._expanded = False
        self._buttons = {}
        self.setFixedWidth(SIDEBAR_COLLAPSED_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._width_animation = QVariantAnimation(self)
        self._width_animation.setDuration(160)
        self._width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._width_animation.valueChanged.connect(self._set_animated_width)

        self._build()
        self._apply_expanded_state(False)
        self.set_active_page(self._active_page)

    def _build(self):
        self._layout = QVBoxLayout(self)
        lay = self._layout
        lay.setContentsMargins(10, 18, 10, 18)
        lay.setSpacing(8)

        self.brand_block = QWidget()
        self.brand_block.setStyleSheet("background: transparent;")
        brand_block_lay = QVBoxLayout(self.brand_block)
        brand_block_lay.setContentsMargins(0, 0, 0, 0)
        brand_block_lay.setSpacing(0)

        self.brand_panel = self._build_brand_panel()
        brand_block_lay.addWidget(self.brand_panel, 0, Qt.AlignmentFlag.AlignHCenter)
        brand_block_lay.addSpacing(8)
        self.brand_divider = QFrame()
        self.brand_divider.setObjectName("sidebarBrandDivider")
        self.brand_divider.setFixedHeight(1)
        self.brand_divider.setStyleSheet(
            "QFrame#sidebarBrandDivider { background-color: rgba(255,255,255,38); border: none; }")
        brand_block_lay.addWidget(self.brand_divider, 0, Qt.AlignmentFlag.AlignHCenter)
        brand_block_lay.addSpacing(10)
        lay.addWidget(self.brand_block)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, label in PAGES:
            btn = self._make_button(tr(label, label), key)
            btn.clicked.connect(lambda _checked=False, k=key: self.page_requested.emit(k))
            lay.addWidget(btn)
            self._group.addButton(btn)
            self._buttons[key] = btn

        lay.addStretch()

    def _build_brand_panel(self):
        panel = QWidget()
        panel.setObjectName("sidebarBrand")
        panel.setFixedHeight(42)
        panel.setStyleSheet("background: transparent;")
        brand_lay = QHBoxLayout(panel)
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(8)

        self.brand_icon = QLabel()
        self.brand_icon.setObjectName("sidebarBrandIcon")
        self.brand_icon.setFixedSize(32, 32)
        self.brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = self._load_brand_pixmap()
        if pix is not None:
            self.brand_icon.setPixmap(pix)
            self.brand_icon.setStyleSheet(
                "QLabel#sidebarBrandIcon { background: transparent; border: none; }")
        else:
            self.brand_icon.setText("PZ")
            self.brand_icon.setStyleSheet("""
                QLabel#sidebarBrandIcon {
                    background-color: rgba(255,255,255,24);
                    border: 1px solid rgba(255,255,255,42);
                    border-radius: 16px;
                    color: #ffffff; font-size: 12px; font-weight: bold;
                }""")
        brand_lay.addWidget(self.brand_icon)

        self.brand_text = QLabel("Precision Zones")
        self.brand_text.setObjectName("sidebarBrandText")
        self.brand_text.setStyleSheet("""
            QLabel#sidebarBrandText {
                background: transparent; color: #ffffff;
                font-size: 12px; font-weight: bold; letter-spacing: 0.4px;
            }""")
        brand_lay.addWidget(self.brand_text)
        brand_lay.addStretch()
        return panel

    def _make_button(self, text, key):
        btn = SidebarNavButton(text)
        btn.setObjectName("sidebarNavButton")
        btn.setProperty("navText", text)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(42)
        btn.setIcon(self._make_icon(key))
        btn.setIconSize(QSize(20, 20))
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setToolTip(text)
        return btn

    def set_active_page(self, page):
        self._active_page = page
        for key, btn in self._buttons.items():
            btn.setChecked(key == page)

    # -------------------------------------------------- hover expand
    def enterEvent(self, event):
        self._apply_expanded_state(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_expanded_state(False)
        super().leaveEvent(event)

    def _apply_expanded_state(self, expanded):
        self._expanded = expanded
        side_margin = 14 if expanded else 11
        self._layout.setContentsMargins(side_margin, 18, side_margin, 18)

        for btn in self._buttons.values():
            btn.setText(btn.property("navText") if expanded else "")
            btn.setToolTip("" if expanded else btn.property("navText"))
            btn.setFixedWidth(172 if expanded else 42)

        self.brand_panel.setFixedWidth(172 if expanded else 32)
        self.brand_block.setFixedWidth(172 if expanded else 42)
        self.brand_text.setVisible(expanded)
        self.brand_divider.setFixedWidth(172 if expanded else 28)

        self.setStyleSheet(self._stylesheet(expanded))
        self._animate_width(SIDEBAR_EXPANDED_WIDTH if expanded else SIDEBAR_COLLAPSED_WIDTH)

    def _animate_width(self, target_width):
        if self.width() == target_width:
            return
        self._width_animation.stop()
        self._width_animation.setStartValue(self.width())
        self._width_animation.setEndValue(target_width)
        self._width_animation.start()

    def _set_animated_width(self, width):
        self.setFixedWidth(int(width))

    def _stylesheet(self, expanded):
        button_text_align = "left" if expanded else "center"
        button_padding = "0 12px 0 10px" if expanded else "0"
        button_width = "172px" if expanded else "42px"
        return f"""
        QFrame#Sidebar {{
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {SIDEBAR_TOP}, stop:1 {SIDEBAR_BOTTOM});
            border: none;
            border-right: 1px solid rgba(20, 30, 35, 180);
        }}
        QPushButton#sidebarNavButton {{
            background-color: transparent;
            color: {SIDEBAR_TEXT};
            border: none; border-radius: 8px;
            font-size: 12px; font-weight: bold;
            text-align: {button_text_align};
            padding: {button_padding};
            min-width: {button_width}; max-width: {button_width};
            min-height: 42px; max-height: 42px;
        }}
        QPushButton#sidebarNavButton:hover {{
            background-color: rgba(255,255,255,22); color: #ffffff;
        }}
        QPushButton#sidebarNavButton:checked {{
            background-color: transparent; color: #ffffff;
        }}
        QPushButton#sidebarNavButton:disabled {{ color: {SIDEBAR_MUTED}; }}
        """

    # -------------------------------------------------- icons
    def _make_icon(self, kind):
        icon = QIcon()
        icon.addPixmap(self._draw_icon(kind, "#E3E9EC"), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(self._draw_icon(kind, "#FFFFFF"), QIcon.Mode.Normal, QIcon.State.On)
        icon.addPixmap(self._draw_icon(kind, "#FFFFFF"), QIcon.Mode.Active, QIcon.State.Off)
        return icon

    def _load_brand_pixmap(self):
        plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(plugin_dir, "icon.png")
        if not os.path.exists(icon_path):
            return None
        raw = QPixmap(icon_path)
        if raw.isNull():
            return None
        square = raw.scaled(26, 26, Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        rounded = QPixmap(26, 26)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, 26, 26)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, square)
        painter.end()
        return rounded

    def _draw_icon(self, kind, color):
        pix = QPixmap(20, 20)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        if kind == "resample":
            # grid 2x2
            painter.drawRect(QRectF(3, 3, 6, 6))
            painter.drawRect(QRectF(11, 3, 6, 6))
            painter.drawRect(QRectF(3, 11, 6, 6))
            painter.drawRect(QRectF(11, 11, 6, 6))
        elif kind == "pca":
            # axes + scatter
            painter.drawLine(3, 17, 17, 17)
            painter.drawLine(3, 17, 3, 3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            for (x, y) in ((7, 13), (10, 9), (13, 6), (9, 14)):
                painter.drawEllipse(QPointF(x, y), 1.3, 1.3)
        elif kind == "zones":
            # stacked layers
            painter.drawPolygon(QPointF(10, 3), QPointF(17, 7), QPointF(10, 11), QPointF(3, 7))
            painter.drawPolyline(QPointF(3, 11), QPointF(10, 15), QPointF(17, 11))
        elif kind == "filter":
            # funnel
            painter.drawPolyline(QPointF(3, 4), QPointF(17, 4), QPointF(11, 11),
                                 QPointF(11, 17), QPointF(9, 15), QPointF(9, 11),
                                 QPointF(3, 4))
        else:  # analysis — bar chart
            painter.drawLine(3, 17, 17, 17)
            painter.drawRect(QRectF(5, 11, 3, 6))
            painter.drawRect(QRectF(10, 8, 3, 9))
            painter.drawRect(QRectF(15, 5, 3, 12))

        painter.end()
        return pix
