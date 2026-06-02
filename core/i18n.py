# -*- coding: utf-8 -*-
"""Internationalization via Qt's translation system.

English is the source language. Translations live in ``i18n/precision_zones_<lang>.qm``
and are selected from the QGIS UI locale (``locale/userLocale``), mirroring AGLgis.
Wrap every user-facing string with ``tr("English source")``; dynamic strings use
an English template with ``{}`` placeholders followed by ``.format(...)``.
"""
import os

from qgis.PyQt.QtCore import QCoreApplication, QTranslator

try:
    from qgis.core import QgsSettings
except Exception:  # pragma: no cover - QgsSettings always present in QGIS
    QgsSettings = None

CONTEXT = "PrecisionZones"

# Module-global so the installed translator is not garbage-collected.
_translator = None


def tr(message: str) -> str:
    """Translate an English source string for the active locale."""
    return QCoreApplication.translate(CONTEXT, message)


def qgis_locale_lang() -> str:
    """Two-letter QGIS UI locale (e.g. 'pt', 'en'); 'en' if unavailable."""
    try:
        if QgsSettings is not None:
            locale = QgsSettings().value("locale/userLocale", "en_US") or "en_US"
            return locale[:2].lower()
    except Exception:
        pass
    return "en"


def install_translator(plugin_dir: str):
    """Load and install the .qm matching the QGIS UI locale (if any).

    Languages map QGIS' two-letter locale to our .qm names (pt -> pt_BR,
    zh -> zh_CN). Falls back to the English source when no .qm matches.
    """
    global _translator
    try:
        locale = "en_US"
        if QgsSettings is not None:
            locale = QgsSettings().value("locale/userLocale", "en_US") or "en_US"
        lang = locale[:2].lower()
        qm_lang = {"pt": "pt_BR", "zh": "zh_CN"}.get(lang, lang)
        qm_path = os.path.join(plugin_dir, "i18n", f"precision_zones_{qm_lang}.qm")
        if os.path.exists(qm_path):
            translator = QTranslator()
            if translator.load(qm_path):
                QCoreApplication.installTranslator(translator)
                _translator = translator
    except Exception:
        # i18n must never block plugin startup; fall back to English.
        pass
