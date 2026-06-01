# -*- coding: utf-8 -*-
"""Zones tab controller: elbow/silhouette analysis, PNG/CSV export, zone raster."""
import os

import numpy as np
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import QgsRasterLayer, QgsProject

from ..core.deps import DependencyMissing, import_pandas, try_pandas
from ..core.i18n import tr
from ..services import clustering_service, zones_service


def _stem_filename(title: str) -> str:
    return title.replace("/", "-").replace(":", "-")


def _nome_base_zonas(k: int, fonte_tag: str, pcs) -> str:
    if fonte_tag == "PCA":
        pcs_txt = f", PCs={pcs}" if pcs else ""
        return tr("Zones (k={}, PCA{})").format(k, pcs_txt)
    return tr("Zones (k={}, Orig)").format(k)


def _elbow_base_name(tag, kminmax, pcs) -> str:
    kmin, kmax = kminmax if kminmax else (None, None)
    if tag == "PCA" and pcs is not None:
        return tr("Indices (Elbow+Silhouette) – PCA (PCs={}, k={}-{})").format(pcs, kmin, kmax)
    return tr("Indices (Elbow+Silhouette) – Original variables (z-score), k={}-{}").format(kmin, kmax)


class ZonesController:
    def __init__(self, iface, dialog, session, notifier):
        self.iface = iface
        self.dialog = dialog
        self.session = session
        self.notifier = notifier

    # ------------------------------------------------ elbow + silhouette
    def run_elbow(self):
        dlg = self.dialog
        ses = self.session
        try:
            pd = import_pandas()

            use_pca = dlg.radPCA.isChecked() if getattr(dlg, "radPCA", None) is not None else True

            if use_pca:
                if ses.pca_transformada is None:
                    self.notifier.warning(dlg, tr("Error"),
                                          tr("Run PCA first or select 'Original variables'."))
                    return
                pcs = int(dlg.pcSelector.currentText())
                dados = ses.pca_transformada[:, :pcs]
                fonte_str = tr("PCA (PCs={})").format(pcs)
                ses._ultima_pcs = pcs
                ses._ultima_fonte_tag = "PCA"
            else:
                if ses.matriz_variaveis_originais is None:
                    self.notifier.warning(dlg, tr("Error"),
                                          tr("Run the resampling/extraction step first."))
                    return
                dados = clustering_service.standardize(ses.matriz_variaveis_originais)
                fonte_str = tr("Original variables (z-score)")
                ses._ultima_pcs = None
                ses._ultima_fonte_tag = "Orig"

            k_min = dlg.clusterMinSpin.value()
            k_max = dlg.clusterMaxSpin.value()
            ses._ultimo_kminmax = (k_min, k_max)

            elbow = clustering_service.elbow_silhouette(dados, k_min, k_max)
            ks, inercia, silhuetas = elbow.ks, elbow.inertia, elbow.silhouettes

            dlg.indicesTable.setRowCount(len(ks))
            dlg.indicesTable.setColumnCount(3)
            dlg.indicesTable.setHorizontalHeaderLabels([
                tr("k"), tr("Inertia"), tr("Silhouette")])
            for i, (k, iner, sil) in enumerate(zip(ks, inercia, silhuetas)):
                dlg.indicesTable.setItem(i, 0, QtWidgets.QTableWidgetItem(str(k)))
                dlg.indicesTable.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{iner:.2f}"))
                dlg.indicesTable.setItem(i, 2, QtWidgets.QTableWidgetItem(
                    "" if np.isnan(sil) else f"{sil:.4f}"))

            try:
                from qgis.PyQt.QtWidgets import QHeaderView
                hdr = dlg.indicesTable.horizontalHeader()
                hdr.setStretchLastSection(True)
                hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
                hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
                hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            except Exception:
                pass

            ses.tabela_elbow = pd.DataFrame({
                "Clusters": ks,
                "Inércia": inercia,
                tr("Silhouette"): silhuetas
            })

            ax = dlg.elbowAxes
            ax.clear()
            old_twin = getattr(dlg, "_elbowTwinAx", None)
            if old_twin is not None:
                try:
                    old_twin.remove()
                except Exception:
                    pass
                dlg._elbowTwinAx = None

            l1, = ax.plot(ks, inercia, marker='o', label=tr("Inertia"))
            ax.set_xlabel(tr("Number of clusters (k)"))
            ax.set_ylabel(tr("Inertia"))
            ax.set_title(tr("Elbow + Silhouette – {}").format(fonte_str))

            twin = ax.twinx()
            dlg._elbowTwinAx = twin
            twin.grid(False)
            l2, = twin.plot(ks, silhuetas, marker='s', linestyle='--', color='red',
                            label=tr("Silhouette"))
            twin.set_ylabel(tr("Silhouette (−1 to 1)"))
            ax.legend([l1, l2], [l1.get_label(), l2.get_label()], loc='best')
            dlg.elbowCanvas.draw()

            self.notifier.info(dlg, tr("Analysis completed"),
                               tr("Elbow + Silhouette analysis finished successfully."))
        except DependencyMissing as e:
            self.notifier.warning(dlg, tr("Missing dependency"),
                                  e.user_message())
        except Exception as e:
            self.notifier.critical(dlg, tr("Zones analysis error"), str(e))

    # --------------------------------------------------------- exports
    def export_elbow_png(self):
        dlg = self.dialog
        ses = self.session
        if ses.tabela_elbow is None:
            self.notifier.warning(dlg, tr("Error"),
                                  tr("Run zones analysis before exporting."))
            return
        base = _elbow_base_name(ses._ultima_fonte_tag or "Orig", ses._ultimo_kminmax, ses._ultima_pcs)
        sugestao = _stem_filename(base + ".png")
        caminho, _ = QFileDialog.getSaveFileName(
            dlg, tr("Save plot (PNG)"), sugestao,
            tr("PNG (*.png)"))
        if not caminho:
            return
        if not caminho.lower().endswith(".png"):
            caminho += ".png"
        try:
            dlg.elbowCanvas.figure.savefig(caminho, dpi=300, bbox_inches="tight")
            self.notifier.info(dlg, tr("Export completed"),
                               tr("Plot saved to:\n{}").format(caminho))
        except Exception as e:
            self.notifier.critical(dlg, tr("Export error"), str(e))

    def export_elbow_csv(self):
        dlg = self.dialog
        ses = self.session
        if try_pandas() is None:
            self.notifier.warning(dlg, tr("Missing dependency"),
                                  tr("This feature requires 'pandas'."))
            return
        if ses.tabela_elbow is None:
            self.notifier.warning(dlg, tr("Error"),
                                  tr("Run zones analysis before exporting."))
            return
        base = _elbow_base_name(ses._ultima_fonte_tag or "Orig", ses._ultimo_kminmax, ses._ultima_pcs)
        sugestao = _stem_filename(base + ".csv")
        caminho, _ = QFileDialog.getSaveFileName(
            dlg, tr("Save results (CSV)"), sugestao,
            tr("CSV (*.csv)"))
        if not caminho:
            return
        if not caminho.lower().endswith(".csv"):
            caminho += ".csv"
        try:
            ses.tabela_elbow.to_csv(caminho, index=False, encoding="utf-8-sig")
            self.notifier.info(dlg, tr("Export completed"),
                               tr("Results saved to:\n{}").format(caminho))
        except Exception as e:
            self.notifier.critical(dlg, tr("Export error"), str(e))

    # ----------------------------------------------- generate zone raster
    def generate_zones(self):
        dlg = self.dialog
        ses = self.session
        try:
            use_pca = dlg.radPCA.isChecked() if getattr(dlg, "radPCA", None) is not None else True

            if use_pca and ses.pca_transformada is None:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("Run PCA before generating zones (or select 'Original variables')."))
                return
            if (not use_pca) and ses.matriz_variaveis_originais is None:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("Run the resampling/extraction step first."))
                return

            n_zonas = dlg.finalClusterSpin.value()

            if use_pca:
                pcs = dlg.pcSelector.currentIndex() + 1
                dados = ses.pca_transformada[:, :pcs]
                modo_tag = "PCA"
            else:
                dados = clustering_service.standardize(ses.matriz_variaveis_originais)
                modo_tag = "Orig"
                pcs = None

            zonas = clustering_service.final_kmeans(dados, n_zonas)

            df = ses.dados_amostrados.copy()
            df["Zona"] = zonas + 1

            contorno_nome = dlg.vectorLayerCombo.currentText()
            if not contorno_nome:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("Select a valid boundary layer."))
                return
            contorno_layer = ses.vector_layers[contorno_nome]
            # Points (X,Y) live on the resampling grid, which may be an
            # auto-estimated UTM CRS — use that, not the raw boundary CRS.
            crs_authid = ses.ref_crs_authid or contorno_layer.crs().authid()

            if ses.ref_gt is None or ses.grid_shape is None:
                self.notifier.warning(dlg, tr("Error"),
                                      tr("Reference grid not available. Run the resampling step."))
                return

            if not ses.pasta_exportacao:
                pasta = QFileDialog.getExistingDirectory(
                    dlg, tr("Choose a folder to save zones"))
                if not pasta:
                    return
                ses.pasta_exportacao = pasta

            layer_title = _nome_base_zonas(n_zonas, modo_tag, pcs if use_pca else None)
            out_basename = f"zonas_manejo_k{n_zonas}_{modo_tag}.tif"
            out_path = os.path.join(ses.pasta_exportacao, out_basename)

            zones_service.rasterize_zones(df, crs_authid, ses.ref_gt, ses.grid_shape, out_path)

            layer_raster = QgsRasterLayer(out_path, layer_title)
            if not layer_raster.isValid():
                raise Exception(tr("Failed to load generated raster."))

            QgsProject.instance().addMapLayer(layer_raster)
            dlg.atualizar_lista_rasters()

            self.notifier.info(dlg, tr("Zones generated"),
                               tr("Zones were generated and saved to:\n{}").format(out_path))
        except DependencyMissing as e:
            self.notifier.warning(dlg, tr("Missing dependency"),
                                  e.user_message())
        except Exception as e:
            self.notifier.critical(dlg, tr("Error generating zones"), str(e))
