# -*- coding: utf-8 -*-
"""Precision Zones — QGIS plugin entry point.

Thin orchestration layer: builds the view, the shared session, the notifier and
the per-tab controllers, then wires the dialog's widgets to controller methods.
All UI lives in view/, all backend in services/, glue in controllers/.
"""
import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer

from .core.session import PZSession
from .core.notify import Notifier
from .core.qt_compat import wa_delete_on_close
from .core.i18n import install_translator
from .view.main_dialog import PrecisionZonesDialog
from .controllers.resample_ctrl import ResampleController
from .controllers.pca_ctrl import PCAController
from .controllers.zones_ctrl import ZonesController
from .controllers.filter_ctrl import FilterController
from .controllers.analysis_ctrl import AnalysisController


class PrecisionZonesPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        install_translator(self.plugin_dir)
        self.dialog = None
        self.session = PZSession()
        self.notifier = Notifier(iface)

    # ---------------------------- GUI lifecycle ----------------------------
    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.action = QAction(QIcon(icon_path), "Precision Zones", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Precision Zones", self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("Precision Zones", self.action)

    def run(self):
        self.dialog = PrecisionZonesDialog(None)
        self.dialog.session = self.session
        self.dialog.setModal(False)
        self.dialog.setAttribute(wa_delete_on_close(), True)

        # Controllers
        resample = ResampleController(self.iface, self.dialog, self.session, self.notifier)
        pca = PCAController(self.iface, self.dialog, self.session, self.notifier)
        zones = ZonesController(self.iface, self.dialog, self.session, self.notifier)
        flt = FilterController(self.iface, self.dialog, self.session, self.notifier)
        analysis = AnalysisController(self.iface, self.dialog, self.session, self.notifier)
        # keep references alive for the dialog's lifetime
        self._controllers = (resample, pca, zones, flt, analysis)

        d = self.dialog
        # Resampling tab
        d.executarButton.clicked.connect(resample.run)
        # PCA tab
        d.pcaButton.clicked.connect(pca.run_pca)
        d.exportButton.clicked.connect(pca.export_report)
        d.exportPathButton.clicked.connect(pca.choose_export_folder)
        d.btnExportPCRaster.clicked.connect(pca.export_selected_pc)
        d.btnExportAllPCRasters.clicked.connect(pca.export_all_pcs)
        # Zones tab
        d.executarZonasButton.clicked.connect(zones.run_elbow)
        d.exportElbowButton.clicked.connect(zones.export_elbow_png)
        d.exportZonasButton.clicked.connect(zones.export_elbow_csv)
        d.gerarZonasButton.clicked.connect(zones.generate_zones)
        # Mode filter tab
        d.executarFiltroButton.clicked.connect(flt.apply)
        # Analysis tab
        d.botaoCarregarCSV.clicked.connect(analysis.load_csv)
        d.executarAnaliseButton.clicked.connect(analysis.variance_reduction)
        if hasattr(d, "exportarBoxplotsButton"):
            d.exportarBoxplotsButton.clicked.connect(analysis.export_boxplots)

        # Populate layer combos + session lookups
        d.vectorLayerCombo.clear()
        self.session.vector_layers = {}
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                self.session.vector_layers[layer.name()] = layer
                d.vectorLayerCombo.addItem(layer.name())

        d.rasterListWidget.clear()
        self.session.raster_layers = {}
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer):
                self.session.raster_layers[layer.name()] = layer
                d.rasterListWidget.addItem(layer.name())

        d.atualizar_lista_rasters()
        d.show()
