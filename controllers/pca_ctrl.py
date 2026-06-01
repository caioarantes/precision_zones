# -*- coding: utf-8 -*-
"""PCA tab controller: run PCA, export report/folder, export PC rasters."""
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QFileDialog

from ..core.deps import DependencyMissing
from ..core.i18n import tr
from ..core.raster_io import read_ref_metadata_from_layer, find_layer_by_name
from qgis.core import QgsRasterLayer
from ..services import pca_service, export_service


class PCAController:
    def __init__(self, iface, dialog, session, notifier):
        self.iface = iface
        self.dialog = dialog
        self.session = session
        self.notifier = notifier

    # ---------------------------------------------------------------- PCA
    def run_pca(self):
        dlg = self.dialog
        ses = self.session
        try:
            result = pca_service.run_pca(ses.dados_amostrados)
        except DependencyMissing as e:
            self.notifier.warning(dlg, tr("Dependência ausente", "Missing dependency"),
                                  e.user_message())
            return
        except ValueError as e:
            self.notifier.warning(dlg, tr("Erro", "Error"), str(e))
            return
        except Exception as e:
            self.notifier.critical(dlg, tr("Erro na PCA", "PCA error"), str(e))
            return

        ses.pca_transformada = result.scores
        ses.pca_scores = result.scores
        ses.relatorio_pca = result.relatorio_pca
        ses.variancia_explicada = result.variancia_explicada

        dlg.pcaTable.setRowCount(len(result.variance_pct))
        dlg.pcaTable.setColumnCount(4)
        dlg.pcaTable.setHorizontalHeaderLabels([
            tr("Componente", "Component"),
            tr("Autovalor (λ)", "Eigenvalue (λ)"),
            tr("Variância (%)", "Variance (%)"),
            tr("Acumulada (%)", "Cumulative (%)")
        ])
        for i, (lam, v, a) in enumerate(zip(result.eigenvalues, result.variance_pct,
                                            result.cumulative_pct)):
            dlg.pcaTable.setItem(i, 0, QtWidgets.QTableWidgetItem(f"PC{i+1}"))
            dlg.pcaTable.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{lam:.6f}"))
            dlg.pcaTable.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{v:.2f}"))
            dlg.pcaTable.setItem(i, 3, QtWidgets.QTableWidgetItem(f"{a:.2f}"))

        try:
            from qgis.PyQt.QtWidgets import QHeaderView
            hdr = dlg.pcaTable.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            hdr.setStretchLastSection(True)
        except Exception:
            pass

        dlg.popular_combo_pcs(len(result.variance_pct))

        self.notifier.info(dlg, tr("PCA concluída", "PCA finished"),
                           tr("A análise PCA foi executada com sucesso.",
                              "PCA analysis finished successfully."))

    # ---------------------------------------------------------------- export
    def choose_export_folder(self):
        pasta = QFileDialog.getExistingDirectory(
            self.dialog, tr("Escolher pasta para salvar", "Choose folder to save"))
        if pasta:
            self.session.pasta_exportacao = pasta
            if hasattr(self.dialog, "exportPath"):
                self.dialog.exportPath.setText(pasta)

    def export_report(self):
        dlg = self.dialog
        ses = self.session
        if ses.relatorio_pca is None or ses.variancia_explicada is None:
            self.notifier.warning(dlg, tr("Erro", "Error"),
                                  tr("Execute a PCA antes de exportar o relatório.",
                                     "Run PCA before exporting the report."))
            return
        pasta = ses.pasta_exportacao or QFileDialog.getExistingDirectory(
            dlg, tr("Escolher pasta para salvar", "Choose folder to save"))
        if not pasta:
            return
        try:
            export_service.save_pca_report(ses.relatorio_pca, ses.variancia_explicada, pasta)
            self.notifier.info(dlg, tr("Exportado", "Exported"),
                               tr(f"Arquivos salvos em:\n{pasta}", f"Files saved to:\n{pasta}"))
        except Exception as e:
            self.notifier.critical(dlg, tr("Erro", "Error"), str(e))

    # -------------------------------------------------- PC raster exports
    def _ensure_ref_metadata(self) -> bool:
        ses = self.session
        dlg = self.dialog
        if ses.has_ref_metadata():
            return True
        # infer from the first selected raster (or filter/zones combo)
        try:
            sel = dlg.rasterListWidget.selectedItems()
            if not sel:
                name = dlg.rasterFiltroCombo.currentText() or dlg.zonasRasterCombo.currentText()
            else:
                name = sel[0].text()
            if not name:
                return False
            ref_layer = find_layer_by_name(name)
            if ref_layer is None or not isinstance(ref_layer, QgsRasterLayer) or not ref_layer.isValid():
                return False
            meta = read_ref_metadata_from_layer(ref_layer)
            if meta is None:
                return False
            ses.ref_gt, ses.ref_crs_wkt, ses.grid_shape = meta
            return True
        except Exception:
            return False

    def export_selected_pc(self):
        dlg = self.dialog
        ses = self.session
        try:
            if not self._ensure_ref_metadata():
                self.notifier.warning(dlg, tr("Erro", "Error"),
                                      tr("Metadados do raster de referência ausentes. "
                                         "Selecione um raster na aba Reamostragem (ou execute a etapa).",
                                         "Reference raster metadata missing. "
                                         "Select a raster in the Resampling tab (or run that step)."))
                return

            scores, ncomp = ses.resolve_pca_scores()
            if scores is None or ncomp == 0:
                self.notifier.warning(dlg, tr("Erro", "Error"),
                                      tr("Execute a PCA no plugin antes de exportar.",
                                         "Run PCA in the plugin before exporting."))
                return
            # autofill combo if needed
            if dlg.pcExportCombo.count() == 0:
                dlg.popular_combo_pcs(ncomp)

            pc_idx = dlg.pcExportCombo.currentData()
            if pc_idx is None:
                txt = dlg.pcExportCombo.currentText().strip().upper()
                if txt.startswith("PC"):
                    try:
                        pc_idx = int(txt.replace("PC", "")) - 1
                    except Exception:
                        pc_idx = None
            if pc_idx is None or pc_idx < 0:
                self.notifier.warning(dlg, tr("Atenção", "Warning"),
                                      tr("Nenhuma PC selecionada.", "No PC selected."))
                return
            if pc_idx >= ncomp:
                self.notifier.warning(dlg, tr("Atenção", "Warning"),
                                      tr("Índice de PC inválido.", "Invalid PC index."))
                return

            df = ses.dados_amostrados
            if df is None or df.empty or not all(k in df.columns for k in ("X", "Y")):
                self.notifier.warning(dlg, tr("Erro", "Error"),
                                      tr("Pontos (X,Y) não encontrados. Execute a reamostragem no plugin.",
                                         "Points (X,Y) not found. Run resampling in the plugin."))
                return

            sugestao = f"PC{pc_idx+1}.tif"
            out_path, _ = QFileDialog.getSaveFileName(
                dlg, tr("Salvar GeoTIFF da PC", "Save PC GeoTIFF"), sugestao,
                tr("GeoTIFF (*.tif)", "GeoTIFF (*.tif)"))
            if not out_path:
                return
            if not out_path.lower().endswith(".tif"):
                out_path += ".tif"

            export_service.export_pc_raster(scores, pc_idx, df, ses.ref_gt,
                                            ses.ref_crs_wkt, ses.grid_shape, out_path)
            self.notifier.info(dlg, tr("Concluído", "Done"),
                               tr("Raster da PC exportado com sucesso.",
                                  "PC raster exported successfully."))
        except Exception as e:
            self.notifier.critical(dlg, tr("Erro ao exportar", "Export error"), str(e))

    def export_all_pcs(self):
        dlg = self.dialog
        ses = self.session
        try:
            if not self._ensure_ref_metadata():
                self.notifier.warning(dlg, tr("Erro", "Error"),
                                      tr("Metadados do raster de referência ausentes. "
                                         "Selecione um raster na aba Reamostragem (ou execute a etapa).",
                                         "Reference raster metadata missing. "
                                         "Select a raster in the Resampling tab (or run that step)."))
                return

            scores, ncomp = ses.resolve_pca_scores()
            if scores is None or ncomp == 0:
                self.notifier.warning(dlg, tr("Erro", "Error"),
                                      tr("Execute a PCA no plugin antes de exportar.",
                                         "Run PCA in the plugin before exporting."))
                return

            df = ses.dados_amostrados
            if df is None or df.empty or not all(k in df.columns for k in ("X", "Y")):
                self.notifier.warning(dlg, tr("Erro", "Error"),
                                      tr("Pontos (X,Y) não encontrados. Execute a reamostragem no plugin.",
                                         "Points (X,Y) not found. Run resampling in the plugin."))
                return

            out_path, _ = QFileDialog.getSaveFileName(
                dlg, tr("Salvar PCs (multibanda)", "Save PCs (multiband)"), "PCs.tif",
                tr("GeoTIFF (*.tif)", "GeoTIFF (*.tif)"))
            if not out_path:
                return
            if not out_path.lower().endswith(".tif"):
                out_path += ".tif"

            export_service.export_all_pcs_multiband(scores, df, ses.ref_gt,
                                                    ses.ref_crs_wkt, ses.grid_shape, out_path)
            self.notifier.info(dlg, tr("Concluído", "Done"),
                               tr("GeoTIFF multibanda das PCs exportado com sucesso.",
                                  "Multiband PCs GeoTIFF exported successfully."))
        except Exception as e:
            self.notifier.critical(dlg, tr("Erro ao exportar", "Export error"), str(e))
