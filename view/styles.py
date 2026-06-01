# -*- coding: utf-8 -*-
"""Shared UI styles for the Precision Zones dialog (neutral slate palette).

Adapted from the AGLgis view/styles.py token structure, with the green brand
accents replaced by neutral slate (#37474F / #455A64).
"""

# Accent tokens
ACCENT = "#37474F"        # slate
ACCENT_HOVER = "#455A64"
ACCENT_PRESSED = "#2A363C"

# ---------------------------------------------------------------------------
# Dialog base — light grey background, dark text, thin scrollbars
# ---------------------------------------------------------------------------
STYLE_DIALOG = """
QDialog {
    background-color: #f5f5f5;
    color: #212121;
}
QWidget { color: #212121; }
QToolTip {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #cfd8dc;
    padding: 4px 6px;
}
QLineEdit {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}
QLineEdit:focus { border-color: #37474F; }
QScrollBar:vertical { background: #f5f5f5; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #bdbdbd; border-radius: 6px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #f5f5f5; height: 12px; margin: 0; }
QScrollBar::handle:horizontal { background: #bdbdbd; border-radius: 6px; min-width: 20px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""

# ---------------------------------------------------------------------------
# Primary button — solid slate, main call-to-action
# ---------------------------------------------------------------------------
STYLE_BTN_PRIMARY = """
QPushButton {
    background-color: #37474F;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-size: 12px;
    font-weight: bold;
    padding: 8px 16px;
}
QPushButton:hover  { background-color: #455A64; }
QPushButton:pressed { background-color: #2A363C; }
QPushButton:disabled { background-color: #bdbdbd; color: #f5f5f5; }
"""

# ---------------------------------------------------------------------------
# Secondary button — white with slate border, for export/aux actions
# ---------------------------------------------------------------------------
STYLE_BTN_SECONDARY = """
QPushButton {
    background-color: #ffffff;
    color: #37474F;
    border: 1px solid #cfd8dc;
    border-radius: 7px;
    font-size: 11px;
    font-weight: bold;
    padding: 6px 12px;
}
QPushButton:hover { background-color: #eceff1; border-color: #90a4ae; }
QPushButton:pressed { background-color: #cfd8dc; border-color: #37474F; }
QPushButton:disabled { background-color: #eeeeee; color: #9e9e9e; border-color: #e0e0e0; }
"""

# ---------------------------------------------------------------------------
# Help button — circular "?" in the dialog header
# ---------------------------------------------------------------------------
STYLE_BTN_HELP = """
QPushButton {
    background-color: transparent;
    color: #9e9e9e;
    border: 1.5px solid #d0d0d0;
    border-radius: 14px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton:hover { background-color: #f5f5f5; color: #424242; border-color: #bdbdbd; }
"""

# ---------------------------------------------------------------------------
# Page card — white panel, field labels, combos, tables
# ---------------------------------------------------------------------------
STYLE_PAGE = """
QWidget#pzPage { background-color: #f5f5f5; }
QFrame#pzPanel {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 12px;
}
QLabel { background: transparent; border: none; }
QLabel#pzFieldLabel {
    color: #607d8b;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 0.5px;
}
QComboBox {
    combobox-popup: 0;
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #d0d0d0;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
}
QComboBox:focus { border: 1.5px solid #37474F; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #bdbdbd;
    selection-background-color: #eceff1;
    selection-color: #1a1a1a;
    outline: 0;
}
QListWidget, QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
}
QSpinBox {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 6px;
    padding: 3px 6px;
}
QSpinBox:focus { border: 1.5px solid #37474F; }
QGroupBox {
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    margin-top: 8px;
    font-weight: bold;
    color: #455a64;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
"""
