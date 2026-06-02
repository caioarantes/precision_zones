# -*- coding: utf-8 -*-
"""Intro-page dependency panel: live status + install/recheck."""
from qgis.core import QgsApplication

from ..core.i18n import tr
from ..core.deps import check_imports
from .. import extlibs_manager


class DepsController:
    def __init__(self, iface, dialog, session, notifier):
        self.iface = iface
        self.dialog = dialog
        self.session = session
        self.notifier = notifier

    def _saga_available(self) -> bool:
        try:
            reg = QgsApplication.processingRegistry()
            return bool(reg.providerById("sagang") or reg.providerById("saga"))
        except Exception:
            return False

    def refresh(self):
        extlibs_manager.ensure_on_path()
        self.dialog.set_dep_status(check_imports(), self._saga_available())

    def install(self):
        self.dialog.set_deps_installing(True)
        dl = extlibs_manager.start_download()
        dl.download_done.connect(self._on_done)

    def _on_done(self, ok: bool, msg: str):
        self.dialog.set_deps_installing(False)
        if ok:
            extlibs_manager.ensure_on_path()
            self.refresh()
            self.notifier.info(self.dialog, tr("Done"),
                               tr("Dependencies installed."))
        else:
            self.notifier.warning(self.dialog, tr("Missing dependency"),
                                  msg or tr("Could not install dependencies."))
