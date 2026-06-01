# -*- coding: utf-8 -*-
"""Internationalization: default EN, PT only when QGIS is in Portuguese.

Single source of truth for `tr()` — previously duplicated in precision_zones.py
and precision_zones_dialog.py.
"""
import os

from qgis.PyQt.QtCore import QLocale, QSettings


def _resolve_lang_is_pt() -> bool:
    env = (os.environ.get("PZ_FORCE_LANG", "") or "").strip().lower()
    if env.startswith("pt"):
        return True
    if env.startswith("en"):
        return False

    s = QSettings()
    pref = (s.value("PrecisionZones/lang", "auto") or "auto").strip().lower()
    if pref.startswith("pt"):
        return True
    if pref.startswith("en"):
        return False

    override_raw = s.value("locale/overrideFlag", False)
    override = str(override_raw).strip().lower() in ("1", "true", "yes", "y")
    if override:
        ui_locale = (s.value("locale/userLocale", "") or "").strip().lower()
        return ui_locale.startswith("pt")

    return QLocale().name().lower().startswith("pt")


def tr(pt_br: str, en: str) -> str:
    """Default EN; PT only when _resolve_lang_is_pt() is True."""
    return pt_br if _resolve_lang_is_pt() else en
