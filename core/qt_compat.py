# -*- coding: utf-8 -*-
"""Qt5/Qt6 compatibility shims, shared by view and plugin entry."""
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt


def wa_delete_on_close():
    """PyQt5: Qt.WA_DeleteOnClose ; PyQt6: Qt.WidgetAttribute.WA_DeleteOnClose."""
    try:
        return Qt.WA_DeleteOnClose
    except AttributeError:
        return Qt.WidgetAttribute.WA_DeleteOnClose


def align_left_flag():
    try:
        return Qt.AlignLeft  # Qt5
    except AttributeError:
        return Qt.AlignmentFlag.AlignLeft  # Qt6


def set_multiselection(list_widget):
    """SelectionMode enum path differs between Qt5 and Qt6."""
    try:
        list_widget.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)  # Qt5
    except AttributeError:
        list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)  # Qt6


def exec_dialog(dlg):
    """exec_ (Qt5) vs exec (Qt6)."""
    try:
        dlg.exec_()
    except AttributeError:
        dlg.exec()
