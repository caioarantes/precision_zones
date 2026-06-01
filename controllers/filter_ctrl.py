# -*- coding: utf-8 -*-
"""Mode-filter tab controller: SAGA majority filter on a zones raster."""
from qgis.core import QgsProject, QgsRasterLayer

from ..core.i18n import tr
from ..core.raster_io import obter_raster_por_nome
from ..services import filter_service


class FilterController:
    def __init__(self, iface, dialog, session, notifier):
        self.iface = iface
        self.dialog = dialog
        self.session = session
        self.notifier = notifier

    def apply(self):
        dlg = self.dialog
        try:
            nome_raster = dlg.rasterFiltroCombo.currentText().strip()
            raster = obter_raster_por_nome(nome_raster)
            if not raster or not raster.isValid():
                raise Exception(tr("Raster not found."))
            src_path = raster.dataProvider().dataSourceUri().split("|")[0]

            raio = int(dlg.windowSizeSpin.value())
            threshold = (float(dlg.thresholdSpin.value())
                         if hasattr(dlg, "thresholdSpin") else 0.0)

            result = filter_service.apply_majority_filter(
                src_path, raster.crs().authid(), raio, threshold)

            layer_name = tr("{} – majority (r={})").format(raster.name(), result.raio)
            out_layer = QgsRasterLayer(result.out_path, layer_name, "gdal")
            if not out_layer.isValid():
                raise Exception(tr("Invalid/unreadable output."))

            try:
                out_layer.setRenderer(raster.renderer().clone())
                if result.nodata is not None:
                    out_layer.dataProvider().setNoDataValue(1, float(result.nodata))
                out_layer.triggerRepaint()
            except Exception:
                pass

            QgsProject.instance().addMapLayer(out_layer)
            dlg.atualizar_lista_rasters()

            self.notifier.info(
                dlg, tr("Majority filter (SAGA)"),
                tr("Filter applied.\nLayer created: {}").format(layer_name))
        except Exception as e:
            self.notifier.critical(
                dlg, tr("Error applying majority filter"),
                str(e))
