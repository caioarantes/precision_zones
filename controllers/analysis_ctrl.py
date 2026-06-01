# -*- coding: utf-8 -*-
"""Analysis tab controller: load CSV, variance reduction, boxplots."""
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QFileDialog

from ..core.deps import DependencyMissing, import_pandas, try_pandas
from ..core.i18n import tr
from ..core.raster_io import find_layer_by_name
from ..services import variance_service, export_service
from ..services.variance_service import NoZonesData
from ..services.export_service import NoPointsInZones


class AnalysisController:
    def __init__(self, iface, dialog, session, notifier):
        self.iface = iface
        self.dialog = dialog
        self.session = session
        self.notifier = notifier

    # ------------------------------------------------------------ CSV
    def load_csv(self):
        dlg = self.dialog
        pd = try_pandas()
        if pd is None:
            self.notifier.warning(
                dlg, tr("Missing dependency"),
                tr("Reading CSV requires 'pandas'.\n"
                   "Open the Resampling tab and click 'Download dependencies' to install."))
            return
        try:
            caminho, _ = QFileDialog.getOpenFileName(
                dlg, tr("Select CSV"), "",
                tr("CSV files (*.csv)"))
            if not caminho:
                return

            df = pd.read_csv(caminho, sep=None, engine='python', decimal=',')
            colunas = df.columns.tolist()

            dlg.colunaXCombo.clear()
            dlg.colunaYCombo.clear()
            dlg.colunaAtributoCombo.clear()
            dlg.colunaXCombo.addItems(colunas)
            dlg.colunaYCombo.addItems(colunas)
            dlg.colunaAtributoCombo.addItems(colunas)

            self.session.dados_amostrados = df
            self.notifier.info(dlg, tr("Success"),
                               tr("CSV loaded successfully."))
        except Exception as e:
            self.notifier.critical(dlg, tr("Error"),
                                   tr("Failed to read CSV:\n{}").format(e))

    # ------------------------------------------------ variance reduction
    def _zones_raster_path(self):
        name = self.dialog.zonasRasterCombo.currentText()
        layer = find_layer_by_name(name)
        if layer is None:
            return None
        return layer.dataProvider().dataSourceUri().split("|")[0]

    def variance_reduction(self):
        dlg = self.dialog
        ses = self.session
        try:
            raster_path = self._zones_raster_path()
            if raster_path is None:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("Zones raster not found."))
                return

            if ses.dados_amostrados is None:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("No points CSV loaded."))
                return

            col_x = dlg.colunaXCombo.currentText()
            col_y = dlg.colunaYCombo.currentText()
            col_attr = dlg.colunaAtributoCombo.currentText()
            if not col_x or not col_y or not col_attr:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("Select X, Y and attribute columns."))
                return

            result = variance_service.variance_reduction(
                ses.dados_amostrados, col_x, col_y, col_attr, raster_path)
        except NoZonesData as e:
            self.notifier.warning(dlg, tr("Error"), str(e))
            return
        except DependencyMissing as e:
            self.notifier.warning(dlg, tr("Missing dependency"),
                                  e.user_message())
            return
        except ValueError as e:
            self.notifier.warning(dlg, tr("Error"), str(e))
            return
        except Exception as e:
            self.notifier.critical(dlg, tr("Error"),
                                   tr("Variance Reduction failed:\n{}").format(e))
            return

        if result.dropped:
            self.notifier.status(tr("Analysis"),
                                 tr("Ignored {} points outside the zones raster.").format(result.dropped))

        colZona = tr("Zone")
        colMedia = tr("Mean")
        colVar = tr("Variance")
        colArea = tr("Area (ha)")

        dlg.resultadoTabela.setRowCount(len(result.ui_rows))
        dlg.resultadoTabela.setColumnCount(5)
        dlg.resultadoTabela.setHorizontalHeaderLabels([colZona, colMedia, colVar, "n", colArea])
        for i, (z, media, var, n, area_ha) in enumerate(result.ui_rows):
            dlg.resultadoTabela.setItem(i, 0, QtWidgets.QTableWidgetItem(str(int(z))))
            dlg.resultadoTabela.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{media:.2f}"))
            dlg.resultadoTabela.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{var:.2f}"))
            dlg.resultadoTabela.setItem(i, 3, QtWidgets.QTableWidgetItem(str(int(n))))
            dlg.resultadoTabela.setItem(i, 4, QtWidgets.QTableWidgetItem(f"{area_ha:.2f}"))

        vr = result.vr_percent
        dlg.resultadoVRLabel.setText(tr("VR: {}%").format(vr))

        salvar, _ = QFileDialog.getSaveFileName(
            dlg, tr("Save CSV (per-zone statistics)"), "",
            tr("CSV Files (*.csv)"))
        if salvar:
            try:
                pd = import_pandas()
                export_df = result.export_df
                extra = {c: "" for c in export_df.columns}
                extra[colZona] = tr("Total VR%")
                extra[colMedia] = f"{vr:.2f}"
                df_out = pd.concat([export_df, pd.DataFrame([extra])], ignore_index=True)
                df_out.to_csv(salvar, index=False)
                self.notifier.info(
                    dlg, tr("Success"),
                    tr("File saved successfully to:\n{}\n\n(Total VR = {}%)").format(salvar, vr))
            except Exception as e:
                self.notifier.critical(dlg, tr("Error"),
                                       tr("Variance Reduction failed:\n{}").format(e))

    # ------------------------------------------------------- boxplots
    def export_boxplots(self):
        dlg = self.dialog
        ses = self.session
        try:
            if ses.dados_amostrados is None:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("No points CSV loaded."))
                return

            col_x = dlg.colunaXCombo.currentText()
            col_y = dlg.colunaYCombo.currentText()
            col_attr = dlg.colunaAtributoCombo.currentText()
            if not col_x or not col_y or not col_attr:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("Select X, Y and attribute columns."))
                return

            raster_path = self._zones_raster_path()
            if raster_path is None:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("Zones raster not found."))
                return

            out_path, _ = QFileDialog.getSaveFileName(
                dlg, tr("Save boxplots"), "",
                tr("PNG (*.png)"))
            if not out_path:
                return
            if not out_path.lower().endswith(".png"):
                out_path += ".png"

            export_service.build_boxplots(ses.dados_amostrados, col_x, col_y, col_attr,
                                          raster_path, out_path)
            self.notifier.info(dlg, tr("Success"),
                               tr("Boxplots saved to:\n{}").format(out_path))
        except (ValueError, NoPointsInZones) as e:
            self.notifier.warning(dlg, tr("Error"), str(e))
        except DependencyMissing as e:
            self.notifier.warning(dlg, tr("Missing dependency"),
                                  e.user_message())
        except Exception as e:
            self.notifier.critical(dlg, tr("Error"),
                                   tr("Failed to export boxplots:\n{}").format(e))
