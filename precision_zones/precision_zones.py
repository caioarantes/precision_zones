from qgis.PyQt.QtWidgets import QMessageBox, QAction, QFileDialog
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext,
)
from qgis import processing
from .precision_zones_dialog import PrecisionZonesDialog
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QLocale, QSettings
import os
import tempfile
import uuid
import math
import numpy as np
from osgeo import gdal  # para ler metadados do raster de referência


# ---------------------------------- i18n (default EN; PT só se QGIS estiver em PT) ----------------------------------
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
    return pt_br if _resolve_lang_is_pt() else en
# ------------------------------------------------------------------------------------------------


# ---------------------------------- Dependências Python (soft import) ----------------------------------
try:
    import pandas as pd
except Exception:
    pd = None
# -------------------------------------------------------------------------------------------------------


def obter_raster_por_nome(nome):
    for camada in QgsProject.instance().mapLayers().values():
        if isinstance(camada, QgsRasterLayer) and camada.name() == nome:
            return camada
    return None


# ---------------------------------- Util: Silhueta para K-Means ----------------------------------
def _silhouette_kmeans(X, labels, max_samples=10000, random_state=0):
    try:
        from sklearn.metrics import silhouette_score
    except Exception:
        return float("nan")
    n = X.shape[0]
    if n > max_samples:
        rng = np.random.default_rng(random_state)
        idx = rng.choice(n, size=max_samples, replace=False)
        return float(silhouette_score(X[idx], labels[idx], metric="euclidean"))
    else:
        return float(silhouette_score(X, labels, metric="euclidean"))


class PrecisionZonesPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dialog = None
        self.plugin_dir = os.path.dirname(__file__)
        self.dados_amostrados = None
        self.pasta_exportacao = None
        self.referencia_raster = None
        self.vector_layers = {}
        self.raster_layers = {}

        # metadados que o dialog usa para exportar rasters
        self.ref_gt = None
        self.ref_crs_wkt = None
        self.grid_shape = None  # (rows, cols)
        self.res_alvo = None    # resolução em metros

        # nomes bonitos / rastreio
        self._ultima_fonte_tag = None   # "PCA" ou "Orig"
        self._ultima_pcs = None         # int ou None
        self._ultimo_kminmax = None     # (kmin, kmax)

    # ---------------------------- Helpers de nome ----------------------------
    def _nome_base_zonas(self, k: int, fonte_tag: str, pcs: int | None) -> str:
        if fonte_tag == "PCA":
            pcs_txt = f", PCs={pcs}" if pcs else ""
            return tr(f"Zonas (k={k}, PCA{pcs_txt})", f"Zones (k={k}, PCA{pcs_txt})")
        else:
            return tr(f"Zonas (k={k}, Orig)", f"Zones (k={k}, Orig)")

    def _nome_elbow(self) -> tuple[str, str]:
        tag = self._ultima_fonte_tag or "Elbow"
        kmin, kmax = self._ultimo_kminmax if self._ultimo_kminmax else (None, None)
        pcs = self._ultima_pcs
        if tag == "PCA" and pcs is not None:
            base = tr(f"Elbow (PCA, PCs={pcs}, k={kmin}-{kmax})",
                      f"Elbow (PCA, PCs={pcs}, k={kmin}-{kmax})")
        elif tag in ("Orig", "Elbow"):
            base = tr(f"Elbow (Orig, k={kmin}-{kmax})",
                      f"Elbow (Orig, k={kmin}-{kmax})")
        else:
            base = tr(f"Elbow ({tag}, k={kmin}-{kmax})",
                      f"Elbow ({tag}, k={kmin}-{kmax})")
        return base + ".png", base + ".csv"

    def _stem_filename(self, title: str) -> str:
        return title.replace("/", "-").replace(":", "-")

    # ---------------------------- GUI lifecycle ----------------------------
    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(QIcon(icon_path), "Precision Zones", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Precision Zones", self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("Precision Zones", self.action)

    def run(self):
        self.dialog = PrecisionZonesDialog(None)
        self.dialog._plugin = self
        self.dialog.setModal(False)
        self.dialog.setAttribute(Qt.WA_DeleteOnClose, True)

        # Conexões
        self.dialog.botaoCarregarCSV.clicked.connect(self.carregar_csv_variancia)
        self.dialog.pcaButton.clicked.connect(self.executar_pca)
        self.dialog.exportButton.clicked.connect(self.exportar_relatorio_pca)
        self.dialog.exportPathButton.clicked.connect(self.selecionar_pasta_exportacao)
        self.dialog.executarZonasButton.clicked.connect(self.executar_zonas)
        self.dialog.exportElbowButton.clicked.connect(self.exportar_elbow_png)
        self.dialog.exportZonasButton.clicked.connect(self.exportar_elbow_csv)
        self.dialog.gerarZonasButton.clicked.connect(self.gerar_zonas_manejo)
        self.dialog.executarFiltroButton.clicked.connect(self.aplicar_filtro_modal)
        self.dialog.executarAnaliseButton.clicked.connect(self.executar_reducao_variancia)
        if hasattr(self.dialog, "exportarBoxplotsButton"):
            self.dialog.exportarBoxplotsButton.clicked.connect(self.exportar_boxplots_analises)

        # Popular combos iniciais
        self.dialog.vectorLayerCombo.clear()
        self.vector_layers = {}
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                self.vector_layers[layer.name()] = layer
                self.dialog.vectorLayerCombo.addItem(layer.name())

        self.dialog.rasterListWidget.clear()
        self.raster_layers = {}
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer):
                self.raster_layers[layer.name()] = layer
                self.dialog.rasterListWidget.addItem(layer.name())

        self.dialog.executarButton.clicked.connect(self.executar)
        self.dialog.atualizar_lista_rasters()
        self.dialog.show()

    # --------------------- Util: limpeza de dados --------------------------
    def _limpar_dataframe(self, df):
        if pd is None or df is None or getattr(df, "empty", True):
            return df

        df = df.copy()
        var_cols = [c for c in df.columns if c not in ['X', 'Y', 'valor']]

        for c in var_cols:
            df[c] = pd.to_numeric(df[c], errors='coerce')

        for c in var_cols:
            s = df[c].astype(float)
            s[~np.isfinite(s)] = np.nan
            df[c] = s

        sentinelas = set([-9999, -99999, -32768, 32767, 65535])
        LIM_ABS = 1e19
        for c in var_cols:
            s = df[c].astype(float)
            s[np.isin(s, list(sentinelas))] = np.nan
            s[np.abs(s) > LIM_ABS] = np.nan
            df[c] = s

        n0 = len(df)
        df = df.dropna(subset=var_cols)
        n1 = len(df)

        zero_var_cols = []
        for c in var_cols:
            serie = pd.to_numeric(df[c], errors='coerce')
            if serie.nunique(dropna=True) <= 1:
                zero_var_cols.append(c)
        if zero_var_cols:
            df = df.drop(columns=zero_var_cols, errors='ignore')

        if n1 < n0:
            self.iface.messageBar().pushMessage(
                tr("Limpeza de dados", "Data cleaning"),
                tr(f"Removidas {n0 - n1} linhas com faltas/NoData.",
                   f"Removed {n0 - n1} rows with missing/NoData."),
                level=0
            )
        if zero_var_cols:
            self.iface.messageBar().pushMessage(
                tr("Limpeza de dados", "Data cleaning"),
                tr(f"Removidas colunas sem variação: {', '.join(zero_var_cols)}.",
                   f"Removed zero-variance columns: {', '.join(zero_var_cols)}."),
                level=0
            )

        return df

    # --------------------- Reamostragem & Extração ------------------------
    def executar(self):
        if pd is None:
            QMessageBox.warning(
                self.dialog,
                tr("Dependência ausente", "Missing dependency"),
                tr("Este recurso requer o pacote Python 'pandas'.\n"
                   "Abra a aba Reamostragem e clique em 'Ver instruções' para instalar.",
                   "This feature requires the Python package 'pandas'.\n"
                   "Open the Resampling tab and click 'Show instructions' to install.")
            )
            return

        # 0) Camadas / parâmetros
        vetor_nome = self.dialog.vectorLayerCombo.currentText()
        if not vetor_nome:
            QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                tr("Selecione um vetor de contorno.",
                                   "Select a boundary vector layer."))
            return
        contorno_layer = self.vector_layers[vetor_nome]

        # Exigir contorno em metros (UTM) para pedir resolução em m
        if contorno_layer.crs().isGeographic():
            QMessageBox.critical(
                self.dialog,
                tr("CRS inválido", "Invalid CRS"),
                tr("O contorno está em graus (CRS geográfico). Reprojete o contorno para UTM (metros) antes de continuar.",
                   "Boundary is in degrees (geographic CRS). Reproject the boundary to UTM (meters) before continuing.")
            )
            return

        itens = self.dialog.rasterListWidget.selectedItems()
        if not itens:
            QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                tr("Selecione ao menos um raster.",
                                   "Select at least one raster."))
            return
        rasters = [self.raster_layers[item.text()] for item in itens]

        res_txt = self.dialog.resolucaoLineEdit.text().strip()
        try:
            resolucao = float(res_txt)
            if resolucao <= 0:
                raise ValueError
        except Exception:
            QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                tr("Informe a resolução como número (ex.: 2 ou 2.5).",
                                   "Provide resolution as a number (e.g., 2 or 2.5)."))
            return
        self.res_alvo = resolucao

        # 1) Construir GRADE ÚNICA (snap) com base no contorno + resolução
        extent_cont = contorno_layer.extent()
        x_min = extent_cont.xMinimum()
        x_max = extent_cont.xMaximum()
        y_min = extent_cont.yMinimum()
        y_max = extent_cont.yMaximum()

        x0 = math.floor(x_min / resolucao) * resolucao
        y0 = math.ceil(y_max / resolucao) * resolucao
        cols = int(math.ceil((x_max - x0) / resolucao))
        rows = int(math.ceil((y0 - y_min) / resolucao))
        x1 = x0 + cols * resolucao
        y1 = y0 - rows * resolucao
        extent_str = f"{x0},{x1},{y1},{y0}"  # xmin,xmax,ymin,ymax

        # metadados da grade
        self.ref_gt = (x0, resolucao, 0.0, y0, 0.0, -resolucao)
        self.ref_crs_wkt = contorno_layer.crs().toWkt()
        self.grid_shape = (rows, cols)

        context = QgsProcessingContext()
        context.setTransformContext(QgsProject.instance().transformContext())
        feedback = QgsProcessingFeedback()

        imagens_recortadas = []
        primeira_saida = None

        import tempfile, shutil, uuid, pathlib

        base_tmp = tempfile.mkdtemp(prefix="pz_warp_")  # pasta própria e persistente
        primeira_saida = None
        imagens_recortadas = []

        for i, raster in enumerate(rasters):
            try:
                self.iface.messageBar().pushMessage(
                    tr("Processando", "Processing"),
                    tr(f"Reprojetando/reamostrando {raster.name()}...", f"Reprojecting/resampling {raster.name()}..."),
                    level=0
                )

                # --- 0) Preparos básicos / checagens ---
                tgt_crs = contorno_layer.crs()
                src_crs = raster.crs()

                # Extent do contorno no CRS alvo (já está)
                cont_ext = contorno_layer.extent()
                x_min, x_max = cont_ext.xMinimum(), cont_ext.xMaximum()
                y_min, y_max = cont_ext.yMinimum(), cont_ext.yMaximum()
                extent_str = f"{x_min},{x_max},{y_min},{y_max}"

                # Extent do raster reprojetado para o CRS do contorno (para checar interseção)
                try:
                    trf = QgsCoordinateTransform(src_crs, tgt_crs, QgsProject.instance().transformContext())
                    src_ext_tgt = trf.transformBoundingBox(raster.extent())
                    intersects = (
                        (src_ext_tgt.xMaximum() > x_min) and (src_ext_tgt.xMinimum() < x_max) and
                        (src_ext_tgt.yMaximum() > y_min) and (src_ext_tgt.yMinimum() < y_max)
                    )
                    if not intersects:
                        self.iface.messageBar().pushMessage(
                            tr("Aviso", "Warning"),
                            tr(f"{raster.name()}: raster não intersecta o contorno após reprojeção — pulando.",
                               f"{raster.name()}: raster does not intersect boundary after reprojection — skipping."),
                            level=1
                        )
                        continue
                except Exception:
                    # Se der algo na transformação, prossegue e deixa o Warp tentar
                    pass

                # Calcula nº de pixels com a resolução pedida (garante pelo menos 1x1)
                width_px  = int(np.ceil((x_max - x_min) / resolucao))
                height_px = int(np.ceil((y_max - y_min) / resolucao))
                if width_px < 1:  width_px = 1
                if height_px < 1: height_px = 1

                # --- 1) Warp/Reproject para CRS do contorno + resolução + extent do contorno ---
                warp_tmp = os.path.join(tempfile.gettempdir(), f"_pz_warp_{uuid.uuid4().hex[:8]}.tif")
                out_clip = os.path.join(self.plugin_dir, f"{raster.name()}_clip.tif")

                produced = False
                try:
                    res_warp = processing.run("gdal:warpreproject", {
                        'INPUT': raster.source(),
                        'SOURCE_CRS': src_crs.authid(),
                        'TARGET_CRS': tgt_crs.authid(),
                        'RESAMPLING': 1,                               # bilinear
                        'NODATA': None,
                        'TARGET_RESOLUTION': [resolucao, resolucao],
                        'TARGET_EXTENT': extent_str,
                        'TARGET_EXTENT_CRS': tgt_crs.authid(),
                        'MULTITHREADING': True,
                        'DATA_TYPE': 0,
                        'EXTRA': f'-tap -ts {width_px} {height_px}',   # força grade e alinhamento
                        'OUTPUT': warp_tmp
                    }, context=context, feedback=feedback)

                    cand = res_warp.get('OUTPUT', warp_tmp)
                    produced = cand and os.path.exists(cand)
                except Exception:
                    produced = False

                # --- 1b) Fallback com gdal.Warp se o provider não gerou saída ---
                if not produced:
                    try:
                        gdal.Warp(
                            destNameOrDestDS=warp_tmp,
                            srcDSOrSrcDSTab=raster.source(),
                            format="GTiff",
                            dstSRS=tgt_crs.authid(),
                            xRes=resolucao, yRes=resolucao,
                            outputBounds=(x_min, y_min, x_max, y_max),
                            resampleAlg=gdal.GRA_Bilinear,
                            warpOptions=["MULTITHREAD=YES", "TARGET_ALIGNED_PIXELS=TRUE"],
                            creationOptions=["COMPRESS=LZW", "TILED=YES"],
                        )
                        produced = os.path.exists(warp_tmp)
                    except Exception:
                        produced = False

                if not produced:
                    raise Exception(tr("Warp não gerou saída.", "Warp produced no output."))

                # --- 2) Clip pela máscara (mantém grade do warp) ---
                self.iface.messageBar().pushMessage(
                    tr("Processando", "Processing"),
                    tr(f"Recortando {raster.name()} pelo contorno...", f"Clipping {raster.name()} by boundary..."),
                    level=0
                )
                res_clip = processing.run("gdal:cliprasterbymasklayer", {
                    'INPUT': warp_tmp,
                    'MASK': contorno_layer,
                    'SOURCE_CRS': tgt_crs.authid(),
                    'TARGET_CRS': tgt_crs.authid(),
                    'RESAMPLING': 0,       # nearest no clip
                    'NODATA': None,
                    'ALPHA_BAND': False,
                    'CROP_TO_CUTLINE': True,
                    'KEEP_RESOLUTION': True,
                    'TARGET_RESOLUTION': None,
                    'OUTPUT': out_clip
                }, context=context, feedback=feedback)

                layer_saida = QgsRasterLayer(out_clip, f"{raster.name()}_clip")
                if not layer_saida.isValid():
                    raise Exception(tr("Camada de saída inválida.", "Invalid output layer."))
                imagens_recortadas.append(layer_saida)

                if i == 0:
                    primeira_saida = layer_saida
                    self.referencia_raster = layer_saida

            except Exception as e:
                QMessageBox.critical(self.dialog, tr("Erro", "Error"),
                                     tr(f"Erro ao processar {raster.name()}: {str(e)}",
                                        f"Failed processing {raster.name()}: {str(e)}"))
                return
                


        if primeira_saida is None:
            QMessageBox.critical(self.dialog, tr("Erro", "Error"),
                                 tr("Falha geral na reamostragem.", "Resampling failed."))
            return

        # 4) Gera centroides e extrai valores
        try:
            self.iface.messageBar().pushMessage(
                tr("Processando", "Processing"),
                tr("Gerando pontos centroide...", "Generating centroid points..."),
                level=0
            )

            pontos_result = processing.run("native:pixelstopoints", {
                'INPUT_RASTER': primeira_saida.source(),
                'RASTER_BAND': 1,
                'FIELD_NAME': 'valor',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }, context=context, feedback=feedback)

            output_pontos = pontos_result['OUTPUT']
            layer_pontos = QgsVectorLayer(output_pontos, "Pontos_centroides", "ogr") \
                           if isinstance(output_pontos, str) else output_pontos

            if not layer_pontos.isValid():
                raise Exception(tr("Camada de pontos inválida.", "Invalid points layer."))

            for raster in imagens_recortadas:
                nome_campo = raster.name()
                self.iface.messageBar().pushMessage(
                    tr("Processando", "Processing"),
                    tr(f"Extraindo valores de {nome_campo}...",
                       f"Extracting values from {nome_campo}..."),
                    level=0
                )

                result = processing.run("qgis:rastersampling", {
                    'INPUT': layer_pontos,
                    'RASTERCOPY': raster,
                    'COLUMN_PREFIX': nome_campo + '_',
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                }, context=context, feedback=feedback)

                output_amostras = result['OUTPUT']
                layer_pontos = QgsVectorLayer(output_amostras, "Amostras_atribuidas", "ogr") \
                               if isinstance(output_amostras, str) else output_amostras

                if not layer_pontos.isValid():
                    raise Exception(tr(f"Falha ao carregar camada com valores de {nome_campo}.",
                                       f"Failed to load layer with values from {nome_campo}."))

            features = []
            campos = [f.name() for f in layer_pontos.fields()]
            for feat in layer_pontos.getFeatures():
                attrs = feat.attributes()
                if None not in attrs:
                    geom = feat.geometry()
                    if geom and not geom.isMultipart():
                        ponto = geom.asPoint()
                        linha = {'X': ponto.x(), 'Y': ponto.y()}
                        linha.update({campos[i]: attr for i, attr in enumerate(attrs)})
                        features.append(linha)

            df = pd.DataFrame(features)
            df = self._limpar_dataframe(df)
            if df is None or df.empty:
                QMessageBox.warning(
                    self.dialog,
                    tr("Sem dados válidos", "No valid data"),
                    tr("Após a limpeza, não restaram linhas válidas para análise.",
                       "After cleaning, no valid rows remained for analysis.")
                )
                return

            self.dados_amostrados = df

            dfnum = self.dados_amostrados.select_dtypes(include=[np.number]).copy()
            for col_drop in ['X', 'Y', 'valor']:
                if col_drop in dfnum.columns:
                    dfnum = dfnum.drop(columns=[col_drop])
            self.matriz_variaveis_originais = dfnum.values
            self.colunas_variaveis_originais = dfnum.columns.tolist()

            # checagem opcional: confirma resolução do arquivo
            try:
                ref_path = primeira_saida.dataProvider().dataSourceUri().split("|")[0]
                ds_chk = gdal.Open(ref_path)
                gt_chk = ds_chk.GetGeoTransform()
                rx, ry = gt_chk[1], abs(gt_chk[5])
                if abs(rx - resolucao) > 1e-6 or abs(ry - resolucao) > 1e-6:
                    self.iface.messageBar().pushWarning(
                        tr("Aviso de resolução", "Resolution warning"),
                        tr(f"O raster resultante está em {rx:.6f}×{ry:.6f} (m), diferente do valor digitado {resolucao}.",
                           f"Result raster is {rx:.6f}×{ry:.6f} (m), different from requested {resolucao}.")
                    )
            except Exception:
                pass

            QMessageBox.information(
                self.dialog,
                tr("Etapa concluída", "Step completed"),
                tr("Dados reamostrados, extraídos e armazenados na memória (com limpeza) com sucesso!",
                   "Data resampled, extracted and stored in memory (with cleaning) successfully!")
            )

        except Exception as e:
            QMessageBox.critical(self.dialog, tr("Erro", "Error"),
                                 tr(f"Erro ao gerar/extrair valores: {str(e)}",
                                    f"Failed to generate/extract values: {str(e)}"))
            return

    # ------------------------------ PCA ------------------------------------
    def executar_pca(self):
        try:
            if pd is None:
                QMessageBox.warning(
                    self.dialog,
                    tr("Dependência ausente", "Missing dependency"),
                    tr("Este recurso requer 'pandas'.\n"
                       "Abra a aba Reamostragem e clique em 'Ver instruções' para instalar.",
                       "This feature requires 'pandas'.\n"
                       "Open the Resampling tab and click 'Show instructions' to install.")
                )
                return

            try:
                from sklearn.preprocessing import StandardScaler
                from sklearn.decomposition import PCA
            except Exception:
                QMessageBox.warning(
                    self.dialog,
                    tr("Dependência ausente", "Missing dependency"),
                    tr("Este recurso requer 'scikit-learn'.\n"
                       "Abra a aba Reamostragem e clique em 'Ver instruções' para instalar.",
                       "This feature requires 'scikit-learn'.\n"
                       "Open the Resampling tab and click 'Show instructions' to install.")
                )
                return

            if self.dados_amostrados is None or self.dados_amostrados.empty:
                QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                    tr("Nenhum dado carregado. Execute a etapa de reamostragem.",
                                       "No data loaded. Run the resampling step first."))
                return

            df = self.dados_amostrados.copy()
            colunas_usar = [c for c in df.columns if c not in ['X', 'Y', 'valor']]
            if not colunas_usar:
                QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                    tr("Sem variáveis numéricas para PCA.",
                                       "No numeric variables for PCA."))
                return

            dados = df[colunas_usar]
            if dados.shape[0] < 2:
                QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                    tr("Dados insuficientes para PCA (menos de 2 linhas).",
                                       "Insufficient data for PCA (less than 2 rows)."))
                return

            dados_padronizados = StandardScaler().fit_transform(dados)
            pca = PCA()
            componentes = pca.fit_transform(dados_padronizados)

            # Guarda para outras etapas/exportação
            self.pca_transformada = componentes
            self.pca_scores = componentes  # alias para o dialog

            variancias = pca.explained_variance_ratio_ * 100.0
            acumulada = variancias.cumsum()
            
            
            autovalores = pca.explained_variance_  # λ

            self.dialog.pcaTable.setRowCount(len(variancias))
            self.dialog.pcaTable.setColumnCount(4)
            self.dialog.pcaTable.setHorizontalHeaderLabels([
                tr("Componente", "Component"),
                tr("Autovalor (λ)", "Eigenvalue (λ)"),
                tr("Variância (%)", "Variance (%)"),
                tr("Acumulada (%)", "Cumulative (%)")
            ])
            for i, (lam, v, a) in enumerate(zip(autovalores, variancias, acumulada)):
                self.dialog.pcaTable.setItem(i, 0, QtWidgets.QTableWidgetItem(f"PC{i+1}"))
                self.dialog.pcaTable.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{lam:.6f}"))
                self.dialog.pcaTable.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{v:.2f}"))
                self.dialog.pcaTable.setItem(i, 3, QtWidgets.QTableWidgetItem(f"{a:.2f}"))

            # (opcional) ajustar o cabeçalho para ficar bonitinho
            try:
                from qgis.PyQt.QtWidgets import QHeaderView
                hdr = self.dialog.pcaTable.horizontalHeader()
                hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
                hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
                hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
                hdr.setStretchLastSection(True)
            except Exception:
                pass

            self.relatorio_pca = pd.DataFrame(
                pca.components_.T,
                columns=[f"PC{i+1}" for i in range(len(variancias))],
                index=colunas_usar
            ).reset_index().rename(columns={"index": "Variável"})

            # inclui autovalor no CSV de variância
            self.variancia_explicada = pd.DataFrame({
                "Componente": [f"PC{i+1}" for i in range(len(variancias))],
                "Autovalor (λ)": autovalores,
                "Variância (%)": variancias,
                "Acumulada (%)": acumulada
            })

            # ---- Preenche e habilita combos automaticamente ----
            n_components = len(variancias)
            if hasattr(self.dialog, "popular_combo_pcs"):
                self.dialog.popular_combo_pcs(n_components)

            QMessageBox.information(self.dialog,
                                    tr("PCA concluída", "PCA finished"),
                                    tr("A análise PCA foi executada com sucesso.",
                                       "PCA analysis finished successfully."))

        except Exception as e:
            QMessageBox.critical(self.dialog, tr("Erro na PCA", "PCA error"), str(e))

    # -------------------- Elbow + Silhueta (PCA ou Originais) -------------------------
    def executar_zonas(self):
        try:
            try:
                from sklearn.cluster import KMeans
                from sklearn.preprocessing import StandardScaler
                from sklearn.metrics import silhouette_score
            except Exception:
                QMessageBox.warning(
                    self.dialog,
                    tr("Dependência ausente", "Missing dependency"),
                    tr("Este recurso requer 'scikit-learn'.\n"
                       "Abra a aba Reamostragem e clique em 'Ver instruções' para instalar.",
                       "This feature requires 'scikit-learn'.\n"
                       "Open the Resampling tab and click 'Show instructions' to install.")
                )
                return

            if pd is None:
                QMessageBox.warning(
                    self.dialog,
                    tr("Dependência ausente", "Missing dependency"),
                    tr("Este recurso requer 'pandas'.\n"
                       "Abra a aba Reamostragem e clique em 'Ver instruções' para instalar.",
                       "This feature requires 'pandas'.\n"
                       "Open the Resampling tab and click 'Show instructions' to install.")
                )
                return

            use_pca = getattr(self.dialog, "radPCA", None)
            use_pca = use_pca.isChecked() if use_pca is not None else True

            if use_pca:
                if not hasattr(self, "pca_transformada"):
                    QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                        tr("Execute a PCA antes ou selecione 'Variáveis originais'.",
                                           "Run PCA first or select 'Original variables'."))
                    return
                pcs = int(self.dialog.pcSelector.currentText())
                dados = self.pca_transformada[:, :pcs]
                fonte_str = tr(f"PCA (PCs={pcs})", f"PCA (PCs={pcs})")
                self._ultima_pcs = pcs
                self._ultima_fonte_tag = "PCA"
            else:
                if not hasattr(self, "matriz_variaveis_originais"):
                    QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                        tr("Execute a etapa de reamostragem/extração primeiro.",
                                           "Run the resampling/extraction step first."))
                    return
                from sklearn.preprocessing import StandardScaler
                dados = StandardScaler().fit_transform(self.matriz_variaveis_originais)
                fonte_str = tr("Variáveis originais (z-score)", "Original variables (z-score)")
                self._ultima_pcs = None
                self._ultima_fonte_tag = "Orig"

            k_min = self.dialog.clusterMinSpin.value()
            k_max = self.dialog.clusterMaxSpin.value()
            self._ultimo_kminmax = (k_min, k_max)

            ks = list(range(k_min, k_max + 1))
            inercia = []
            silhuetas = []

            for k in ks:
                kmeans = KMeans(n_clusters=k, random_state=0, n_init=10)
                kmeans.fit(dados)
                inercia.append(kmeans.inertia_)

                try:
                    labels = kmeans.labels_
                    s = silhouette_score(dados, labels) if len(np.unique(labels)) > 1 else float("nan")
                except Exception:
                    s = float("nan")
                silhuetas.append(s)

            self.dialog.indicesTable.setRowCount(len(ks))
            self.dialog.indicesTable.setColumnCount(3)
            self.dialog.indicesTable.setHorizontalHeaderLabels([
                tr("k", "k"),
                tr("Inércia", "Inertia"),
                tr("Silhueta", "Silhouette"),
            ])
            for i, (k, iner, sil) in enumerate(zip(ks, inercia, silhuetas)):
                self.dialog.indicesTable.setItem(i, 0, QtWidgets.QTableWidgetItem(str(k)))
                self.dialog.indicesTable.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{iner:.2f}"))
                self.dialog.indicesTable.setItem(i, 2, QtWidgets.QTableWidgetItem("" if np.isnan(sil) else f"{sil:.4f}"))

            try:
                hdr = self.dialog.indicesTable.horizontalHeader()
                hdr.setStretchLastSection(True)
                from qgis.PyQt.QtWidgets import QHeaderView
                hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
                hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
                hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            except Exception:
                pass

            self.tabela_elbow = pd.DataFrame({
                "Clusters": ks,
                "Inércia": inercia,
                tr("Silhueta", "Silhouette"): silhuetas
            })

            ax = self.dialog.elbowAxes
            ax.clear()

            old_twin = getattr(self, "_elbowTwinAx", None)
            if old_twin is not None:
                try:
                    old_twin.remove()
                except Exception:
                    pass
                self._elbowTwinAx = None

            l1, = ax.plot(ks, inercia, marker='o', label=tr("Inércia", "Inertia"))
            ax.set_xlabel(tr("Número de Clusters (k)", "Number of clusters (k)"))
            ax.set_ylabel(tr("Inércia", "Inertia"))
            ax.set_title(tr(f"Elbow + Silhueta – {fonte_str}", f"Elbow + Silhouette – {fonte_str}"))

            twin = ax.twinx()
            self._elbowTwinAx = twin
            twin.grid(False)
            l2, = twin.plot(ks, silhuetas, marker='s', linestyle='--', color='red',
                            label=tr("Silhueta", "Silhouette"))
            twin.set_ylabel(tr("Silhueta (−1 a 1)", "Silhouette (−1 to 1)"))

            ax.legend([l1, l2], [l1.get_label(), l2.get_label()], loc='best')

            self.dialog.elbowCanvas.draw()

            QMessageBox.information(
                self.dialog,
                tr("Análise concluída", "Analysis completed"),
                tr("Análise de clusters por Elbow + Silhueta finalizada com sucesso.",
                   "Elbow + Silhouette analysis finished successfully.")
            )

        except Exception as e:
            QMessageBox.critical(self.dialog, tr("Erro na análise de zonas", "Zones analysis error"), str(e))

    def exportar_elbow_png(self):
        if not hasattr(self, "tabela_elbow"):
            QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                tr("Execute a análise de zonas antes de exportar.",
                                   "Run zones analysis before exporting."))
            return

        tag = self._ultima_fonte_tag or "Orig"
        kmin, kmax = self._ultimo_kminmax if self._ultimo_kminmax else (None, None)
        pcs = self._ultima_pcs
        if tag == "PCA" and pcs is not None:
            base = tr(f"Índices (Elbow+Silhueta) – PCA (PCs={pcs}, k={kmin}-{kmax})",
                      f"Indices (Elbow+Silhouette) – PCA (PCs={pcs}, k={kmin}-{kmax})")
        else:
            base = tr(f"Índices (Elbow+Silhueta) – Variáveis originais (z-score), k={kmin}-{kmax}",
                      f"Indices (Elbow+Silhouette) – Original variables (z-score), k={kmin}-{kmax}")

        sugestao = self._stem_filename(base + ".png")
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.dialog,
            tr("Salvar gráfico (PNG)", "Save plot (PNG)"),
            sugestao,
            tr("PNG (*.png)", "PNG (*.png)")
        )
        if not caminho:
            return
        if not caminho.lower().endswith(".png"):
            caminho += ".png"
        try:
            self.dialog.elbowCanvas.figure.savefig(caminho, dpi=300, bbox_inches="tight")
            QMessageBox.information(self.dialog, tr("Exportação concluída", "Export completed"),
                                    tr(f"Gráfico salvo em:\n{caminho}",
                                       f"Plot saved to:\n{caminho}"))
        except Exception as e:
            QMessageBox.critical(self.dialog, tr("Erro na exportação", "Export error"), str(e))

    def exportar_elbow_csv(self):
        if pd is None:
            QMessageBox.warning(self.dialog, tr("Dependência ausente", "Missing dependency"),
                                tr("Este recurso requer 'pandas'.", "This feature requires 'pandas'."))
            return
        if not hasattr(self, "tabela_elbow"):
            QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                tr("Execute a análise de zonas antes de exportar.",
                                   "Run zones analysis before exporting."))
            return

        tag = self._ultima_fonte_tag or "Orig"
        kmin, kmax = self._ultimo_kminmax if self._ultimo_kminmax else (None, None)
        pcs = self._ultima_pcs
        if tag == "PCA" and pcs is not None:
            base = tr(f"Índices (Elbow+Silhueta) – PCA (PCs={pcs}, k={kmin}-{kmax})",
                      f"Indices (Elbow+Silhouette) – PCA (PCs={pcs}, k={kmin}-{kmax})")
        else:
            base = tr(f"Índices (Elbow+Silhueta) – Variáveis originais (z-score), k={kmin}-{kmax}",
                      f"Indices (Elbow+Silhouette) – Original variables (z-score), k={kmin}-{kmax}")

        sugestao = self._stem_filename(base + ".csv")
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.dialog,
            tr("Salvar resultados (CSV)", "Save results (CSV)"),
            sugestao,
            tr("CSV (*.csv)", "CSV (*.csv)")
        )
        if not caminho:
            return
        if not caminho.lower().endswith(".csv"):
            caminho += ".csv"
        try:
            self.tabela_elbow.to_csv(caminho, index=False, encoding="utf-8-sig")
            QMessageBox.information(self.dialog, tr("Exportação concluída", "Export completed"),
                                    tr(f"Resultados salvos em:\n{caminho}",
                                       f"Results saved to:\n{caminho}"))
        except Exception as e:
            QMessageBox.critical(self.dialog, tr("Erro na exportação", "Export error"), str(e))

    # --------------------- Geração de Zonas Raster --------------------------
    def gerar_zonas_manejo(self):
        try:
            try:
                from sklearn.cluster import KMeans
                from sklearn.preprocessing import StandardScaler
            except Exception:
                QMessageBox.warning(
                    self.dialog,
                    tr("Dependência ausente", "Missing dependency"),
                    tr("Este recurso requer 'scikit-learn'.\n"
                       "Abra a aba Reamostragem e clique em 'Ver instruções' para instalar.",
                       "This feature requires 'scikit-learn'.\n"
                       "Open the Resampling tab and click 'Show instructions' to install.")
                )
                return

            import numpy as np
            from qgis.core import (
                QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY,
                QgsVectorFileWriter, QgsProject
            )
            from PyQt5.QtCore import QVariant

            use_pca = getattr(self.dialog, "radPCA", None)
            use_pca = use_pca.isChecked() if use_pca is not None else True

            if use_pca and not hasattr(self, "pca_transformada"):
                QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                    tr("Execute a PCA antes de gerar zonas (ou selecione 'Variáveis originais').",
                                       "Run PCA before generating zones (or select 'Original variables')."))
                return
            if (not use_pca) and (not hasattr(self, "matriz_variaveis_originais")):
                QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                    tr("Execute a etapa de reamostragem/extração primeiro.",
                                       "Run the resampling/extraction step first."))
                return

            n_zonas = self.dialog.finalClusterSpin.value()

            if use_pca:
                pcs = self.dialog.pcSelector.currentIndex() + 1
                dados = self.pca_transformada[:, :pcs]
                modo_tag = "PCA"
                modo_label = "PCA"
            else:
                dados = StandardScaler().fit_transform(self.matriz_variaveis_originais)
                modo_tag = "Orig"
                modo_label = tr("Orig", "Orig")

            modelo = KMeans(n_clusters=n_zonas, random_state=0, n_init=10)
            zonas = modelo.fit_predict(dados)

            df = self.dados_amostrados.copy()
            df["Zona"] = zonas + 1

            contorno_nome = self.dialog.vectorLayerCombo.currentText()
            if not contorno_nome:
                QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                    tr("Selecione uma camada de contorno válida.",
                                       "Select a valid boundary layer."))
                return
            contorno_layer = self.vector_layers[contorno_nome]
            crs_contorno = contorno_layer.crs()

            mem_layer = QgsVectorLayer(f"Point?crs={crs_contorno.authid()}", "zonas_pts_mem", "memory")
            prov = mem_layer.dataProvider()
            prov.addAttributes([QgsField("Zona", QVariant.Int)])
            mem_layer.updateFields()

            feats = []
            for X, Y, Z in df[["X", "Y", "Zona"]].itertuples(index=False):
                from qgis.core import QgsFeature, QgsGeometry, QgsPointXY
                f = QgsFeature(mem_layer.fields())
                f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(X), float(Y))))
                f.setAttribute("Zona", int(Z))
                feats.append(f)
            prov.addFeatures(feats)
            mem_layer.updateExtents()

            tmp_gpkg = os.path.join(tempfile.gettempdir(), "pz_zonas_pts.gpkg")
            if os.path.exists(tmp_gpkg):
                try:
                    os.remove(tmp_gpkg)
                except Exception:
                    pass

            save_opts = QgsVectorFileWriter.SaveVectorOptions()
            save_opts.driverName = "GPKG"
            save_opts.layerName = "zonas_pts"
            save_opts.fileEncoding = "UTF-8"

            ret = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer, tmp_gpkg, QgsProject.instance().transformContext(), save_opts
            )
            err = ret[0]
            err_msg = ret[1] if len(ret) > 1 else ""
            if err != QgsVectorFileWriter.NoError:
                raise Exception(tr(f"Falha ao salvar GeoPackage temporário: {err_msg}",
                                   f"Failed to save temporary GeoPackage: {err_msg}"))

            pontos_src = QgsVectorLayer(tmp_gpkg + "|layername=zonas_pts", "zonas_pts", "ogr")
            if not pontos_src.isValid():
                raise Exception(tr("Camada temporária (GeoPackage) inválida.",
                                   "Temporary (GeoPackage) layer is invalid."))

            # --- usa a grade de referência calculada na reamostragem ---
            if self.ref_gt is None or self.grid_shape is None:
                raise Exception(tr("Grade de referência não disponível. Execute a etapa de reamostragem.",
                                   "Reference grid not available. Run the resampling step."))
            x0, px, _, y0, _, neg_py = self.ref_gt
            cols = int(self.grid_shape[1])
            rows = int(self.grid_shape[0])
            extent_str = f"{x0},{x0 + cols * px},{y0 - rows * abs(neg_py)},{y0}"
            width_px = cols
            height_px = rows

            if not self.pasta_exportacao:
                pasta = QtWidgets.QFileDialog.getExistingDirectory(
                    self.dialog, tr("Escolher pasta para salvar as zonas", "Choose a folder to save zones")
                )
                if not pasta:
                    return
                self.pasta_exportacao = pasta

            layer_title = self._nome_base_zonas(n_zonas, modo_tag, pcs if use_pca else None)
            out_basename = f"zonas_manejo_k{n_zonas}_{modo_tag}.tif"
            out_path = os.path.join(self.pasta_exportacao, out_basename)

            processing.run("gdal:rasterize", {
                'INPUT': pontos_src,
                'FIELD': 'Zona',
                'BURN': 0,
                'USE_Z': False,
                'UNITS': 0,
                'WIDTH': width_px,
                'HEIGHT': height_px,
                'EXTENT': extent_str,
                'NODATA': 0,
                'INIT': 0,
                'INVERT': False,
                'DATA_TYPE': 2,
                'EXTRA': '',
                'OUTPUT': out_path
            })

            layer_raster = QgsRasterLayer(out_path, layer_title)
            if not layer_raster.isValid():
                raise Exception(tr("Erro ao carregar o raster gerado.",
                                   "Failed to load generated raster."))
            QgsProject.instance().addMapLayer(layer_raster)

            self.dialog.atualizar_lista_rasters()

            QMessageBox.information(self.dialog,
                                    tr("Zonas geradas", "Zones generated"),
                                    tr(f"As zonas foram geradas e salvas em:\n{out_path}",
                                       f"Zones were generated and saved to:\n{out_path}"))

        except Exception as e:
            QMessageBox.critical(self.dialog, tr("Erro ao gerar zonas", "Error generating zones"), str(e))

    #---------------------------------------------------------------------------------
    def _saga_majority_id(self) -> str | None:
        from qgis.core import QgsApplication
        reg = QgsApplication.processingRegistry()
        if reg.algorithmById('sagang:majorityminorityfilter'):
            return 'sagang:majorityminorityfilter'
        if reg.algorithmById('saga:majorityfilter'):
            return 'saga:majorityfilter'
        if reg.algorithmById('sagang:majorityfilter'):
            return 'sagang:majorityfilter'
        return None

    # --------------------------- Filtro Modal -------------------------------
    def aplicar_filtro_modal(self):
        try:
            nome_raster = self.dialog.rasterFiltroCombo.currentText().strip()
            raster = obter_raster_por_nome(nome_raster)
            if not raster or not raster.isValid():
                raise Exception(tr("Raster não encontrado.", "Raster not found."))
            src_path = raster.dataProvider().dataSourceUri().split("|")[0]

            raio = int(self.dialog.windowSizeSpin.value())
            threshold = float(getattr(self.dialog, "thresholdSpin", None).value()) if hasattr(self.dialog, "thresholdSpin") else 0.0
            tipo = 0
            kernel_tipo = 1

            import os, tempfile, uuid, shutil
            import numpy as np
            from osgeo import gdal
            from qgis.core import QgsProcessingContext, QgsProcessingFeedback, QgsApplication

            base = os.path.join(tempfile.gettempdir(), "pzmod_" + uuid.uuid4().hex[:8])
            os.makedirs(base, exist_ok=True)
            p_saga = os.path.join(base, "s")
            p_tif  = os.path.join(base, "s.tif")
            p_aln  = os.path.join(base, "a.tif")
            p_out  = os.path.join(base, "m.tif")

            context = QgsProcessingContext()
            context.setTransformContext(QgsProject.instance().transformContext())
            feedback = QgsProcessingFeedback()
            reg = QgsApplication.processingRegistry()

            if   reg.algorithmById('sagang:majorityminorityfilter'): saga_id = 'sagang:majorityminorityfilter'
            elif reg.algorithmById('saga:majorityfilter'):           saga_id = 'saga:majorityfilter'
            elif reg.algorithmById('sagang:majorityfilter'):         saga_id = 'sagang:majorityfilter'
            else:
                raise Exception(tr("SAGA não disponível. Ative o provedor SAGA em Processamento.",
                                   "SAGA not available. Enable the SAGA provider in Processing."))

            dsA = gdal.Open(src_path)
            if dsA is None:
                raise Exception(tr("Falha ao abrir o raster de entrada.", "Failed to open input raster."))

            gt = dsA.GetGeoTransform()
            xres = abs(gt[1]); yres = abs(gt[5])
            width_px  = int(dsA.RasterXSize)
            height_px = int(dsA.RasterYSize)

            x_min, y_max = gt[0], gt[3]
            x_max = x_min + gt[1] * width_px
            y_min = y_max + gt[5] * height_px
            extent_str = f"{min(x_min,x_max)},{max(x_min,x_max)},{min(y_min,y_max)},{max(y_min,y_max)}"

            bandA = dsA.GetRasterBand(1)
            nodata = bandA.GetNoDataValue()

            zero_bg = False
            if nodata is None:
                try:
                    probe = bandA.ReadAsArray(0, 0, min(256, width_px), min(256, height_px))
                    zero_bg = probe is not None and (probe == 0).any()
                except Exception:
                    zero_bg = False

            params = {
                "INPUT": src_path,
                "TYPE": tipo,
                "THRESHOLD": threshold,
                "KERNEL_TYPE": kernel_tipo,
                "KERNEL_RADIUS": max(1, raio),
                "RESULT": p_saga
            }
            res = processing.run(saga_id, params, context=context, feedback=feedback)
            saga_res = res.get("RESULT", p_saga)

            created = None
            for ext in (".tif", ".sdat", ".sgrd", ".img", ""):
                p = saga_res if saga_res.lower().endswith(ext) else saga_res + ext
                if os.path.exists(p):
                    created = p
                    break
            if created is None:
                raise Exception(tr("SAGA não gerou arquivo de saída.", "SAGA did not produce an output file."))

            def _valid(path):
                try:
                    return gdal.Open(path) is not None
                except Exception:
                    return False

            if not created.lower().endswith(".tif") or not _valid(created):
                processing.run("gdal:translate", {
                    "INPUT": created,
                    "TARGET_CRS": None,
                    "NODATA": None,
                    "COPY_SUBDATASETS": False,
                    "OPTIONS": "",
                    "EXTRA": "",
                    "DATA_TYPE": 0,
                    "OUTPUT": p_tif
                }, context=context, feedback=feedback)
                saga_path = p_tif
            else:
                saga_path = created
            if not _valid(saga_path):
                raise Exception(tr("Saída do SAGA ilegível pelo GDAL.", "SAGA output unreadable by GDAL."))

            aligned_path = p_aln
            ok = False

            try:
                res_warp = processing.run("gdal:warpreproject", {
                    "INPUT": saga_path,
                    "SOURCE_CRS": None,
                    "TARGET_CRS": raster.crs().authid(),
                    "RESAMPLING": 0,
                    "NODATA": nodata if nodata is not None else 0,
                    "TARGET_RESOLUTION": None,
                    "TARGET_EXTENT": extent_str,
                    "TARGET_EXTENT_CRS": raster.crs().authid(),
                    "MULTITHREADING": True,
                    "DATA_TYPE": 2,
                    "EXTRA": f"-tap -ts {width_px} {height_px}",
                    "OUTPUT": p_aln
                }, context=context, feedback=feedback)
                candidate = res_warp.get("OUTPUT", p_aln)
                if candidate and os.path.exists(candidate):
                    if os.path.normpath(candidate) != os.path.normpath(p_aln):
                        import shutil
                        shutil.copyfile(candidate, p_aln)
                    ok = _valid(p_aln)
            except Exception:
                ok = False

            if not ok:
                try:
                    gdal.Warp(
                        destNameOrDestDS=p_aln,
                        srcDSOrSrcDSTab=saga_path,
                        format="GTiff",
                        dstSRS=raster.crs().authid(),
                        outputBounds=(min(x_min, x_max), min(y_min, y_max), max(x_min, x_max), max(y_min, y_max)),
                        width=width_px,
                        height=height_px,
                        resampleAlg=gdal.GRA_NearestNeighbour,
                        dstNodata=(float(nodata) if nodata is not None else 0),
                        warpOptions=["TARGET_ALIGNED_PIXELS=TRUE"],
                        creationOptions=["COMPRESS=LZW", "TILED=YES"]
                    )
                    ok = _valid(p_aln)
                except Exception:
                    ok = False

            if not ok:
                import shutil
                shutil.copyfile(saga_path, p_aln)

            dsAligned = gdal.Open(p_aln)
            if (dsAligned is None or
                dsAligned.RasterXSize != width_px or
                dsAligned.RasterYSize != height_px):
                raise Exception(tr("Warp não criou o arquivo alinhado esperado (a.tif).",
                                   "Warp did not create expected aligned file (a.tif)."))

            dsA = gdal.Open(src_path)
            dsB = gdal.Open(p_aln)
            arrA = dsA.GetRasterBand(1).ReadAsArray()
            arrB = dsB.GetRasterBand(1).ReadAsArray()

            preservar_ids = True
            if preservar_ids:
                if nodata is not None:
                    mask_cmp = (arrA != nodata); fundo_val = nodata
                elif zero_bg:
                    mask_cmp = (arrA != 0);      fundo_val = 0
                else:
                    mask_cmp = np.ones_like(arrA, dtype=bool); fundo_val = None

                valsA = np.unique(arrA[mask_cmp])
                valsB = np.unique(arrB[mask_cmp])
                if fundo_val is not None:
                    valsA = valsA[valsA != fundo_val]
                    valsB = valsB[valsB != fundo_val]

                if (valsA.size > 0) and (valsB.size > 0):
                    areaA = {int(va): int((arrA[mask_cmp] == va).sum()) for va in valsA}
                    ordem_va = sorted(areaA.keys(), key=lambda v: areaA[v], reverse=True)

                    overlap = {int(vb): {} for vb in valsB}
                    for vb in valsB:
                        m_vb = (arrB == vb) & mask_cmp
                        if not m_vb.any():
                            continue
                        for va in valsA:
                            overlap[int(vb)][int(va)] = int(((arrA == va) & m_vb).sum())

                    usados_vb = set()
                    map_vb_to_va = {}
                    for va in ordem_va:
                        melhor_vb, melhor_c = None, -1
                        for vb in valsB:
                            if int(vb) in usados_vb:
                                continue
                            c = overlap.get(int(vb), {}).get(int(va), 0)
                            if c > melhor_c:
                                melhor_c, melhor_vb = c, int(vb)
                        if melhor_vb is not None:
                            map_vb_to_va[melhor_vb] = int(va)
                            usados_vb.add(melhor_vb)

                    if map_vb_to_va:
                        arrB_mapped = arrB.copy()
                        for vb, va in map_vb_to_va.items():
                            arrB_mapped[arrB == vb] = va
                        arrB = arrB_mapped

            if nodata is not None:
                valid = (arrA != nodata); nd_out = nodata
            elif zero_bg:
                valid = (arrA != 0);      nd_out = 0
            else:
                valid = None;             nd_out = None

            out_arr = arrB if valid is None else np.where(valid, arrB, arrA)

            drv = gdal.GetDriverByName("GTiff")
            out_ds = drv.Create(p_out, width_px, height_px, 1, gdal.GDT_UInt16,
                                options=["COMPRESS=LZW", "TILED=YES"])
            out_ds.SetGeoTransform(gt)
            out_ds.SetProjection(dsA.GetProjection())
            out_band = out_ds.GetRasterBand(1)
            if nd_out is not None:
                out_band.SetNoDataValue(float(nd_out))
            out_band.WriteArray(out_arr.astype(np.uint16))
            out_band.FlushCache(); out_ds.FlushCache()
            out_ds = None; dsB = None; dsA = None

            layer_name = tr(f"{raster.name()} – maioria (r={raio})",
                            f"{raster.name()} – majority (r={raio})")
            out_layer = QgsRasterLayer(p_out, layer_name, "gdal")
            if not out_layer.isValid():
                raise Exception(tr("Saída inválida/ilegível.", "Invalid/unreadable output."))

            try:
                out_layer.setRenderer(raster.renderer().clone())
                if nodata is not None:
                    out_layer.dataProvider().setNoDataValue(1, float(nodata))
                out_layer.triggerRepaint()
            except Exception:
                pass

            QgsProject.instance().addMapLayer(out_layer)
            self.dialog.atualizar_lista_rasters()

            QMessageBox.information(
                None,
                tr("Filtro de maioria (SAGA)", "Majority filter (SAGA)"),
                tr(f"Filtro aplicado.\nCamada criada: {layer_name}",
                   f"Filter applied.\nLayer created: {layer_name}")
            )

        except Exception as e:
            QMessageBox.critical(
                None,
                tr("Erro ao aplicar filtro de maioria", "Error applying majority filter"),
                str(e)
            )

    # -------------------- Análises: Redução de Variância --------------------
    def carregar_csv_variancia(self):
        if pd is None:
            QMessageBox.warning(
                None,
                tr("Dependência ausente", "Missing dependency"),
                tr("Para ler o CSV é necessário o 'pandas'.\n"
                   "Abra a aba Reamostragem e clique em 'Ver instruções' para instalar.",
                   "Reading CSV requires 'pandas'.\n"
                   "Open the Resampling tab and click 'Show instructions' to install.")
            )
            return
        try:
            caminho, _ = QFileDialog.getOpenFileName(
                None,
                tr("Selecionar CSV", "Select CSV"),
                "",
                tr("CSV files (*.csv)", "CSV files (*.csv)")
            )
            if not caminho:
                return

            df = pd.read_csv(caminho, sep=None, engine='python', decimal=',')
            colunas = df.columns.tolist()

            self.dialog.colunaXCombo.clear()
            self.dialog.colunaYCombo.clear()
            self.dialog.colunaAtributoCombo.clear()

            self.dialog.colunaXCombo.addItems(colunas)
            self.dialog.colunaYCombo.addItems(colunas)
            self.dialog.colunaAtributoCombo.addItems(colunas)

            self.dados_amostrados = df
            QMessageBox.information(None, tr("Sucesso", "Success"),
                                    tr("CSV carregado com sucesso.", "CSV loaded successfully."))

        except Exception as e:
            QMessageBox.critical(None, tr("Erro", "Error"),
                                 tr(f"Erro ao ler o CSV:\n{e}", f"Failed to read CSV:\n{e}"))

    def executar_reducao_variancia(self):
        import numpy as np
        import pandas as pd
        from osgeo import gdal
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        from qgis.PyQt import QtWidgets
        import math

        try:
            from scipy.stats import t as student_t, skew as scipy_skew
            def ic95(media, std, n):
                if n <= 1 or std is None or np.isnan(std):
                    return (np.nan, np.nan)
                crit = float(student_t.ppf(0.975, df=n-1))
                erro = crit * std / math.sqrt(n)
                return (media - erro, media + erro)
            def skewness(arr):
                return float(scipy_skew(arr, bias=False)) if len(arr) >= 3 else np.nan
        except Exception:
            def ic95(media, std, n):
                if n <= 1 or std is None or np.isnan(std):
                    return (np.nan, np.nan)
                crit = 1.96
                erro = crit * std / math.sqrt(n)
                return (media - erro, media + erro)
            def skewness(arr):
                s = pd.Series(arr, dtype="float64")
                return float(s.skew()) if s.count() >= 3 else np.nan

        colZona  = tr("Zona", "Zone")
        colMedia = tr("Média", "Mean")
        colVar   = tr("Variância", "Variance")
        colN     = "n"
        colArea  = tr("Área (ha)", "Area (ha)")
        colAreaPct = tr("Área (%)", "Area (%)")
        colMediana = tr("Mediana", "Median")
        colCV    = tr("CV (%)", "CV (%)")
        colMin   = tr("Mín", "Min")
        colMax   = tr("Máx", "Max")
        colIClo  = tr("IC95% inf", "95% CI low")
        colICup  = tr("IC95% sup", "95% CI high")

        try:
            nome_zonas = self.dialog.zonasRasterCombo.currentText()
            zonas_layer = None
            for layer in QgsProject.instance().mapLayers().values():
                if layer.name() == nome_zonas:
                    zonas_layer = layer
            if not zonas_layer:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Raster de zonas não encontrado.", "Zones raster not found."))
                return

            raster_path = zonas_layer.dataProvider().dataSourceUri().split("|")[0]
            raster_ds = gdal.Open(raster_path)
            if raster_ds is None:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Falha ao abrir o raster de zonas.", "Failed to open zones raster."))
                return

            gt = raster_ds.GetGeoTransform()
            px_w, px_h = gt[1], gt[5]
            pixel_area = abs(px_w * px_h)
            band = raster_ds.GetRasterBand(1)
            zona_array = band.ReadAsArray().astype(float)
            nodata = band.GetNoDataValue()

            if self.dados_amostrados is None:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Nenhum CSV de pontos foi carregado.", "No points CSV loaded."))
                return

            df_pontos = self.dados_amostrados.copy()
            col_x = self.dialog.colunaXCombo.currentText()
            col_y = self.dialog.colunaYCombo.currentText()
            col_attr = self.dialog.colunaAtributoCombo.currentText()
            if not col_x or not col_y or not col_attr:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Selecione as colunas X, Y e do atributo.",
                                       "Select X, Y and attribute columns."))
                return

            for c in [col_x, col_y, col_attr]:
                df_pontos[c] = pd.to_numeric(df_pontos[c], errors="coerce")
            df_pontos = df_pontos.dropna(subset=[col_x, col_y, col_attr])

            x_min, y_max = gt[0], gt[3]
            x_max = x_min + px_w * raster_ds.RasterXSize
            y_min = y_max + px_h * raster_ds.RasterYSize
            mask_bbox = (
                df_pontos[col_x].between(min(x_min, x_max), max(x_min, x_max)) &
                df_pontos[col_y].between(min(y_min, y_max), max(y_min, y_max))
            )
            dropped = int((~mask_bbox).sum())
            if dropped:
                try:
                    self.iface.messageBar().pushMessage(
                        tr("Análises", "Analysis"),
                        tr(f"Desconsiderados {dropped} pontos fora do raster de zonas.",
                           f"Ignored {dropped} points outside the zones raster."),
                        level=0
                    )
                except Exception:
                    pass
            df_pontos = df_pontos.loc[mask_bbox].copy()
            if df_pontos.empty:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Todos os pontos ficaram fora do raster de zonas.",
                                       "All points are outside the zones raster."))
                return

            zona_valores = {}
            for _, row in df_pontos.iterrows():
                x, y, valor = float(row[col_x]), float(row[col_y]), float(row[col_attr])
                try:
                    col_pix = int((x - gt[0]) / gt[1])
                    row_pix = int((y - gt[3]) / gt[5])
                    z = float(zona_array[row_pix, col_pix])
                    if not np.isfinite(z):
                        continue
                    if nodata is not None and z == nodata:
                        continue
                    if z <= 0:
                        continue
                    z = int(z)
                    zona_valores.setdefault(z, []).append(valor)
                except Exception:
                    continue
            if not zona_valores:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Nenhum valor válido foi identificado nas zonas.",
                                       "No valid values were identified in the zones."))
                return

            vals = zona_array
            valid_mask = np.isfinite(vals) & (vals > 0)
            if nodata is not None:
                valid_mask &= (vals != nodata)
            zona_ids, zona_counts = np.unique(vals[valid_mask].astype(int), return_counts=True)
            area_por_zona_m2 = dict(zip(zona_ids, zona_counts * pixel_area))

            linhas_ui = []
            for z in sorted(zona_valores.keys()):
                s = pd.Series(zona_valores[z], dtype="float64")
                media = float(s.mean())
                var = float(s.var()) if s.count() > 1 else 0.0
                n = int(s.count())
                area_ha = (area_por_zona_m2.get(int(z), np.nan) / 10000.0
                           if int(z) in area_por_zona_m2 else np.nan)
                linhas_ui.append((int(z), media, var, n, area_ha))
            df_ui = pd.DataFrame(linhas_ui, columns=[colZona, colMedia, colVar, colN, colArea])

            self.dialog.resultadoTabela.setRowCount(len(df_ui))
            self.dialog.resultadoTabela.setColumnCount(5)
            self.dialog.resultadoTabela.setHorizontalHeaderLabels([colZona, colMedia, colVar, colN, colArea])
            for i, row in df_ui.iterrows():
                self.dialog.resultadoTabela.setItem(i, 0, QtWidgets.QTableWidgetItem(str(int(row[colZona]))))
                self.dialog.resultadoTabela.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{row[colMedia]:.2f}"))
                self.dialog.resultadoTabela.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{row[colVar]:.2f}"))
                self.dialog.resultadoTabela.setItem(i, 3, QtWidgets.QTableWidgetItem(str(int(row[colN]))))
                self.dialog.resultadoTabela.setItem(i, 4, QtWidgets.QTableWidgetItem(f"{row[colArea]:.2f}"))

            todos_valores = np.concatenate([np.asarray(v, dtype=float) for v in zona_valores.values()])
            var_total = float(pd.Series(todos_valores).var()) if len(todos_valores) > 1 else 0.0
            area_total_ha = df_ui[colArea].sum()
            termo = (df_ui[colArea] / area_total_ha) * df_ui[colVar] if area_total_ha > 0 else 0.0
            vr_percentual = (1 - (termo.sum() / var_total)) * 100 if var_total > 0 else 0.0
            self.dialog.resultadoVRLabel.setText(tr(f"VR: {vr_percentual:.2f}%", f"VR: {vr_percentual:.2f}%"))

            linhas_export = []
            for z in sorted(zona_valores.keys()):
                arr = np.asarray(zona_valores[z], dtype=float)
                s = pd.Series(arr, dtype="float64")
                n = int(s.count())
                media = float(s.mean())
                std = float(s.std(ddof=1)) if n > 1 else np.nan
                mediana = float(s.median())
                q1 = float(s.quantile(0.25))
                q3 = float(s.quantile(0.75))
                iqr = q3 - q1
                vmin = float(s.min())
                vmax = float(s.max())
                cv = float((std / media * 100.0)) if (n > 1 and media != 0) else np.nan
                # skewness
                try:
                    from scipy.stats import skew as scipy_skew
                    sk = float(scipy_skew(arr, bias=False)) if len(arr) >= 3 else np.nan
                except Exception:
                    sk = float(s.skew()) if s.count() >= 3 else np.nan
                # IC95
                try:
                    from scipy.stats import t as student_t
                    if n > 1 and std is not None and not np.isnan(std):
                        crit = float(student_t.ppf(0.975, df=n-1))
                        erro = crit * std / math.sqrt(n)
                        ic_inf, ic_sup = (media - erro), (media + erro)
                    else:
                        ic_inf, ic_sup = (np.nan, np.nan)
                except Exception:
                    if n > 1 and std is not None and not np.isnan(std):
                        erro = 1.96 * std / math.sqrt(n)
                        ic_inf, ic_sup = (media - erro), (media + erro)
                    else:
                        ic_inf, ic_sup = (np.nan, np.nan)

                area_ha = (area_por_zona_m2.get(int(z), np.nan) / 10000.0
                           if int(z) in area_por_zona_m2 else np.nan)
                area_pct = (area_ha / area_total_ha * 100.0) if (area_total_ha and not np.isnan(area_ha)) else np.nan
                var = float(s.var()) if n > 1 else 0.0

                linhas_export.append({
                    colZona: int(z),
                    colN: n,
                    colArea: area_ha,
                    colAreaPct: area_pct,
                    colMedia: media,
                    colMediana: mediana,
                    colCV: cv,
                    colMin: vmin,
                    "Q1": q1,
                    "Q3": q3,
                    colMax: vmax,
                    "IQR": iqr,
                    "Skewness": sk,
                    colIClo: ic_inf,
                    colICup: ic_sup,
                    colVar: var
                })

            df_export = pd.DataFrame(linhas_export)

            salvar, _ = QFileDialog.getSaveFileName(
                None,
                tr("Salvar CSV (estatísticas por zona)", "Save CSV (per-zone statistics)"),
                "",
                tr("CSV Files (*.csv)", "CSV Files (*.csv)")
            )
            if salvar:
                extra = {c: "" for c in df_export.columns}
                extra[colZona] = tr("VR% total", "Total VR%")
                extra[colMedia] = f"{vr_percentual:.2f}"
                df_out = pd.concat([df_export, pd.DataFrame([extra])], ignore_index=True)
                df_out.to_csv(salvar, index=False)
                QMessageBox.information(
                    None,
                    tr("Sucesso", "Success"),
                    tr(f"Arquivo salvo com sucesso em:\n{salvar}\n\n(VR total = {vr_percentual:.2f}%)",
                       f"File saved successfully to:\n{salvar}\n\n(Total VR = {vr_percentual:.2f}%)")
                )

        except Exception as e:
            QMessageBox.critical(None, tr("Erro", "Error"),
                                 tr(f"Falha na Redução de Variância:\n{e}",
                                    f"Variance Reduction failed:\n{e}"))

    # --------------------------- Boxplots -----------------------------------
    def exportar_boxplots_analises(self):
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
        from osgeo import gdal

        try:
            if self.dados_amostrados is None:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Nenhum CSV de pontos foi carregado.", "No points CSV loaded."))
                return

            col_x = self.dialog.colunaXCombo.currentText()
            col_y = self.dialog.colunaYCombo.currentText()
            col_attr = self.dialog.colunaAtributoCombo.currentText()
            if not col_x or not col_y or not col_attr:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Selecione as colunas X, Y e do atributo.",
                                       "Select X, Y and attribute columns."))
                return

            nome_zonas = self.dialog.zonasRasterCombo.currentText()
            zonas_layer = None
            for layer in QgsProject.instance().mapLayers().values():
                if layer.name() == nome_zonas:
                    zonas_layer = layer
            if not zonas_layer:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Raster de zonas não encontrado.", "Zones raster not found."))
                return

            raster_path = zonas_layer.dataProvider().dataSourceUri().split("|")[0]
            ds = gdal.Open(raster_path)
            if ds is None:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Falha ao abrir o raster de zonas.", "Failed to open zones raster."))
                return

            gt = ds.GetGeoTransform()
            band = ds.GetRasterBand(1)
            zona_array = band.ReadAsArray().astype(float)
            nodata = band.GetNoDataValue()

            df_pontos = self.dados_amostrados.copy()
            for c in [col_x, col_y, col_attr]:
                df_pontos[c] = pd.to_numeric(df_pontos[c], errors='coerce')
            df_pontos = df_pontos.dropna(subset=[col_x, col_y, col_attr])

            x_min, y_max = gt[0], gt[3]
            px_w, px_h = gt[1], gt[5]
            x_max = x_min + px_w * ds.RasterXSize
            y_min = y_max + px_h * ds.RasterYSize
            mask_bbox = (
                df_pontos[col_x].between(min(x_min, x_max), max(x_min, x_max)) &
                df_pontos[col_y].between(min(y_min, y_max), max(y_min, y_max))
            )
            df_pontos = df_pontos.loc[mask_bbox].copy()
            if df_pontos.empty:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Todos os pontos ficaram fora do raster de zonas.",
                                       "All points are outside the zones raster."))
                return

            registros = []
            for _, row in df_pontos.iterrows():
                x, y, valor = float(row[col_x]), float(row[col_y]), float(row[col_attr])
                try:
                    c = int((x - gt[0]) / gt[1])
                    r = int((y - gt[3]) / gt[5])
                    z = float(zona_array[r, c])
                    if not np.isfinite(z):
                        continue
                    if nodata is not None and z == nodata:
                        continue
                    if z <= 0:
                        continue
                    registros.append((int(z), float(valor)))
                except Exception:
                    continue

            if not registros:
                QMessageBox.warning(None, tr("Erro", "Error"),
                                    tr("Não foi possível mapear pontos às zonas para o boxplot.",
                                       "Could not map points to zones for the boxplot."))
                return

            colZona  = tr("Zona", "Zone")
            colValor = tr("Valor", "Value")
            dfz = pd.DataFrame(registros, columns=[colZona, colValor]).dropna()

            series = [dfz[colValor].values] + [
                dfz.loc[dfz[colZona] == z, colValor].values
                for z in sorted(dfz[colZona].unique())
            ]
            labels = [tr("Todos", "All")] + [f"Z{z}" for z in sorted(dfz[colZona].unique())]

            out_path, _ = QFileDialog.getSaveFileName(
                None,
                tr("Salvar boxplots", "Save boxplots"),
                "",
                tr("PNG (*.png)", "PNG (*.png)")
            )
            if not out_path:
                return
            if not out_path.lower().endswith(".png"):
                out_path += ".png"

            nplots = len(series)
            fig_w = max(6, 1.8 * nplots)
            fig, ax = plt.subplots(figsize=(fig_w, 4))
            ax.boxplot(series, showfliers=True)
            ax.set_xticklabels(labels)
            ax.set_xlabel(tr("Grupos", "Groups"))
            ax.set_ylabel(col_attr)
            ax.set_title(tr(f"Boxplots – {col_attr} (Todos vs. Zonas)",
                            f"Boxplots – {col_attr} (All vs. Zones)"))
            ax.grid(True, axis='y', linestyle='--', alpha=0.4)
            plt.tight_layout()
            fig.savefig(out_path, dpi=200, bbox_inches='tight')
            plt.close(fig)

            QMessageBox.information(None, tr("Sucesso", "Success"),
                                    tr(f"Boxplots salvos em:\n{out_path}",
                                       f"Boxplots saved to:\n{out_path}"))

        except Exception as e:
            QMessageBox.critical(None, tr("Erro", "Error"),
                                 tr(f"Falha ao exportar boxplots:\n{e}",
                                    f"Failed to export boxplots:\n{e}"))

    # --------------------- Relatório PCA (CSV) & Pasta ----------------------
    def exportar_relatorio_pca(self):
        if pd is None or not hasattr(self, "relatorio_pca") or not hasattr(self, "variancia_explicada"):
            QMessageBox.warning(self.dialog, tr("Erro", "Error"),
                                tr("Execute a PCA antes de exportar o relatório.",
                                   "Run PCA before exporting the report."))
            return
        pasta = self.pasta_exportacao or QtWidgets.QFileDialog.getExistingDirectory(
            self.dialog, tr("Escolher pasta para salvar", "Choose folder to save")
        )
        if not pasta:
            return
        try:
            f1 = os.path.join(pasta, "pca_componentes.csv")
            f2 = os.path.join(pasta, "pca_variancia.csv")
            self.relatorio_pca.to_csv(f1, index=False, encoding="utf-8-sig")
            self.variancia_explicada.to_csv(f2, index=False, encoding="utf-8-sig")
            QMessageBox.information(self.dialog, tr("Exportado", "Exported"),
                                    tr(f"Arquivos salvos em:\n{pasta}",
                                       f"Files saved to:\n{pasta}"))
        except Exception as e:
            QMessageBox.critical(self.dialog, tr("Erro", "Error"), str(e))

    def selecionar_pasta_exportacao(self):
        pasta = QtWidgets.QFileDialog.getExistingDirectory(
            self.dialog, tr("Escolher pasta para salvar", "Choose folder to save")
        )
        if pasta:
            self.pasta_exportacao = pasta
            if hasattr(self.dialog, "exportPath"):
                self.dialog.exportPath.setText(pasta)
