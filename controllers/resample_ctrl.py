# -*- coding: utf-8 -*-
"""Resampling tab controller: read inputs, call resampling_service, store state."""
from ..core.deps import DependencyMissing
from ..core.i18n import tr
from ..services import resampling_service


class ResampleController:
    def __init__(self, iface, dialog, session, notifier):
        self.iface = iface
        self.dialog = dialog
        self.session = session
        self.notifier = notifier

    def run(self):
        dlg = self.dialog
        ses = self.session

        vetor_nome = dlg.vectorLayerCombo.currentText()
        if not vetor_nome:
            self.notifier.warning(dlg, tr("Error"),
                                  tr("Select a boundary vector layer."))
            return
        contorno_layer = ses.vector_layers[vetor_nome]
        # A geographic boundary is auto-reprojected to its UTM CRS by the
        # resampling service (no longer rejected here).

        itens = dlg.rasterListWidget.selectedItems()
        if not itens:
            self.notifier.warning(dlg, tr("Error"),
                                  tr("Select at least one raster."))
            return
        rasters = [ses.raster_layers[item.text()] for item in itens]

        res_txt = dlg.resolucaoLineEdit.text().strip()
        try:
            resolucao = float(res_txt)
            if resolucao <= 0:
                raise ValueError
        except Exception:
            self.notifier.warning(dlg, tr("Error"),
                                  tr("Provide resolution as a number (e.g., 2 or 2.5)."))
            return
        ses.res_alvo = resolucao

        def _progress(title, msg, level=0):
            self.notifier.status(title, msg, level)

        try:
            result = resampling_service.resample_and_extract(
                contorno_layer, rasters, resolucao, progress=_progress)
        except DependencyMissing as e:
            self.notifier.warning(dlg, tr("Missing dependency"),
                                  e.user_message())
            return
        except Exception as e:
            self.notifier.critical(dlg, tr("Error"),
                                   tr("Failed to generate/extract values: {}").format(str(e)))
            return

        # status messages for cleaning
        if result.n_removed > 0:
            self.notifier.status(tr("Data cleaning"),
                                 tr("Removed {} rows with missing/NoData.").format(result.n_removed))
        if result.zero_var_cols:
            self.notifier.status(tr("Data cleaning"),
                                 tr("Removed zero-variance columns: {}.").format(', '.join(result.zero_var_cols)))

        # reference grid metadata always stored
        ses.ref_gt = result.ref_gt
        ses.ref_crs_wkt = result.ref_crs_wkt
        ses.ref_crs_authid = result.target_crs_authid
        ses.grid_shape = result.grid_shape
        ses.referencia_raster = result.referencia_raster

        if result.df is None or result.df.empty:
            self.notifier.warning(dlg, tr("No valid data"),
                                  tr("After cleaning, no valid rows remained for analysis."))
            return

        ses.dados_amostrados = result.df
        ses.matriz_variaveis_originais = result.matriz_variaveis_originais
        ses.colunas_variaveis_originais = result.colunas_variaveis_originais

        msg = tr("Data resampled, extracted and stored in memory (with cleaning) successfully!")
        if result.reprojected:
            msg += "\n\n" + tr("Boundary was in degrees — auto-reprojected to {}.").format(
                result.target_crs_authid)
        self.notifier.info(dlg, tr("Step completed"), msg)
