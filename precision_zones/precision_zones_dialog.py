from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QListWidget, QLineEdit, QTableWidget, QTableWidgetItem,
    QWidget, QSpinBox, QGroupBox, QRadioButton, QCheckBox, QPlainTextEdit,
    QMessageBox, QFileDialog
)
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QLocale, QSettings
from qgis.PyQt.QtGui import QGuiApplication
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer, QgsWkbTypes, QgsApplication
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from osgeo import gdal, osr
import numpy as np
import os


# ---------------------------------- i18n (default EN; PT só se QGIS estiver em PT) ----------------------------------
from qgis.PyQt.QtCore import QLocale, QSettings
import os

def _resolve_lang_is_pt() -> bool:
    """
    Retorna True SOMENTE quando:
      - PZ_FORCE_LANG for 'pt*'  (força PT); ou
      - Preferência do plugin (QSettings) for 'pt*'; ou
      - QGIS estiver com Override e userLocale começando com 'pt'; ou
      - Locale do sistema começar com 'pt'.
    Em QUALQUER outro caso, retorna False (ou seja, usa EN).
    """
    # 1) Ambiente (override para testes)
    env = (os.environ.get("PZ_FORCE_LANG", "") or "").strip().lower()
    if env.startswith("pt"):
        return True
    if env.startswith("en"):
        return False

    s = QSettings()

    # 2) Preferência opcional do plugin (se quiser expor no futuro)
    pref = (s.value("PrecisionZones/lang", "auto") or "auto").strip().lower()
    if pref.startswith("pt"):
        return True
    if pref.startswith("en"):
        return False

    # 3) Idioma da UI do QGIS quando "Override system locale" está ativo
    override_raw = s.value("locale/overrideFlag", False)
    override = str(override_raw).strip().lower() in ("1", "true", "yes", "y")
    if override:
        ui_locale = (s.value("locale/userLocale", "") or "").strip().lower()
        return ui_locale.startswith("pt")

    # 4) Fallback: apenas PT quando o sistema é PT; caso contrário, EN
    return QLocale().name().lower().startswith("pt")

def tr(pt_br: str, en: str) -> str:
    """Default EN; PT somente quando _resolve_lang_is_pt() for True."""
    return pt_br if _resolve_lang_is_pt() else en
# ------------------------------------------------------------------------------------------------


class _DepsHelpDialog(QDialog):
    """Janela de ajuda para instalar dependências (pandas, scikit-learn, SAGA NextGen)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Como instalar dependências", "How to install dependencies"))
        self.resize(560, 420)

        lay = QVBoxLayout(self)

        tabs = QTabWidget()
        lay.addWidget(tabs)

        # --- Tab: Python (pandas + scikit-learn) ---
        py_tab = QWidget()
        tabs.addTab(py_tab, "Python")
        py_lay = QVBoxLayout(py_tab)

        py_lay.addWidget(QLabel(tr(
            "No Windows (QGIS/OSGeo4W):\n1) Abra o 'OSGeo4W Shell' do QGIS.\n"
            "2) Copie e cole os comandos abaixo e pressione Enter.",
            "On Windows (QGIS/OSGeo4W):\n1) Open the 'OSGeo4W Shell' from QGIS.\n"
            "2) Copy & paste the commands below and press Enter."
        )))

        self._cmds = QPlainTextEdit()
        self._cmds.setReadOnly(True)
        self._cmds.setPlainText(
            "python -m pip install --upgrade pip\n"
            "pip install pandas scikit-learn\n"
        )
        py_lay.addWidget(self._cmds)

        btn_copy = QPushButton(tr("Copiar comandos", "Copy commands"))
        btn_copy.clicked.connect(self._copy_cmds)
        py_lay.addWidget(btn_copy, alignment=Qt.AlignLeft)

        # --- Tab: SAGA NextGen ---
        saga_tab = QWidget()
        tabs.addTab(saga_tab, "SAGA")
        sg_lay = QVBoxLayout(saga_tab)

        _sagaHelp = QtWidgets.QLabel(tr(
            "Se 'SAGA NextGen' estiver desmarcado: instale o complemento "
            "'Processing Saga NextGen Provider' em Plugins ▶ Gerenciar e Instalar…",
            "If 'SAGA NextGen' is unchecked: install the 'Processing Saga NextGen Provider' plugin in "
            "Plugins ▶ Manage and Install…"
        ))
        _sagaHelp.setWordWrap(True)
        sg_lay.addWidget(_sagaHelp)

        close_btns = QHBoxLayout()
        close_btn = QPushButton(tr("Fechar", "Close"))
        close_btn.clicked.connect(self.accept)
        close_btns.addStretch(1)
        close_btns.addWidget(close_btn)
        lay.addLayout(close_btns)

    def _copy_cmds(self):
        QGuiApplication.clipboard().setText(self._cmds.toPlainText())
        QMessageBox.information(
            self,
            tr("Copiado", "Copied"),
            tr("Comandos copiados para a área de transferência.", "Commands copied to clipboard.")
        )


class PrecisionZonesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Nome próprio do plugin: fixo em inglês
        self.setWindowTitle("Precision Zones")
        self.resize(600, 520)

        # --- campos internos opcionais (caso o plugin não injete nada) ---
        self.ref_gt = None            # geotransform (6 floats)
        self.ref_crs_wkt = None       # proj WKT
        self.grid_shape = None        # (rows, cols)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ===================== Aba Reamostragem =====================
        self.mainTab = QWidget()
        self.tabs.addTab(self.mainTab, tr("Reamostragem", "Resampling"))

        self.mainLayout = QVBoxLayout(self.mainTab)

        # --------- Checklist de Dependências (Topo da aba) ----------
        self.grpDeps = QGroupBox(tr("Checklist de dependências", "Dependencies checklist"))
        depsLay = QVBoxLayout(self.grpDeps)

        row1 = QHBoxLayout()
        self.chkPandas  = QCheckBox("pandas")
        self.chkSklearn = QCheckBox("scikit-learn (KMeans)")
        self.chkSaga    = QCheckBox("SAGA NextGen")
        for c in (self.chkPandas, self.chkSklearn, self.chkSaga):
            c.setEnabled(False)
        row1.addWidget(self.chkPandas)
        row1.addWidget(self.chkSklearn)
        row1.addWidget(self.chkSaga)
        row1.addStretch(1)
        depsLay.addLayout(row1)

        row2 = QHBoxLayout()
        self.btnDepsHelp = QPushButton(tr("Ver instruções", "Show instructions"))
        self.btnDepsHelp.clicked.connect(self._show_deps_help)
        self.btnDepsRefresh = QPushButton(tr("Reverificar", "Recheck"))
        self.btnDepsRefresh.clicked.connect(self._check_deps)
        row2.addWidget(self.btnDepsHelp)
        row2.addWidget(self.btnDepsRefresh)
        row2.addStretch(1)
        depsLay.addLayout(row2)

        self.mainLayout.addWidget(self.grpDeps)
        # ------------------------------------------------------------

        self.mainLayout.addWidget(QLabel(tr("Camada Vetorial - UTM (contorno):",
                                            "Vector layer - UTM (boundary):")))
        self.vectorLayerCombo = QComboBox()
        self.mainLayout.addWidget(self.vectorLayerCombo)

        self.mainLayout.addWidget(QLabel(tr("Rasters disponíveis:", "Available rasters:")))
        self.rasterListWidget = QListWidget()
        self.rasterListWidget.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.mainLayout.addWidget(self.rasterListWidget)

        self.mainLayout.addWidget(QLabel(tr(
            "Resolução (em metros - use a referência do raster de maior resolução):",
            "Resolution (meters – use the highest-resolution raster as reference):"
        )))
        self.resolucaoLineEdit = QLineEdit()
        self.mainLayout.addWidget(self.resolucaoLineEdit)

        self.executarButton = QPushButton(tr(
            "Executar reamostragem e extrair valores",
            "Run resampling and extract values"
        ))
        self.mainLayout.addWidget(self.executarButton)

        # ===================== Aba PCA =====================
        self.pcaTab = QWidget()
        self.tabs.addTab(self.pcaTab, "PCA")

        self.pcaLayout = QVBoxLayout(self.pcaTab)

        self.pcaButton = QPushButton(tr("Executar PCA", "Run PCA"))
        self.pcaLayout.addWidget(self.pcaButton)

        self.pcaTable = QTableWidget()
        self.pcaTable.setColumnCount(3)
        self.pcaTable.setHorizontalHeaderLabels([
            tr("Componente", "Component"),
            tr("Variância (%)", "Variance (%)"),
            tr("Acumulada (%)", "Cumulative (%)")
        ])
        self.pcaLayout.addWidget(self.pcaTable)

        self.exportPathButton = QPushButton(tr("Escolher pasta para salvar", "Choose folder to save"))
        self.pcaLayout.addWidget(self.exportPathButton)

        self.exportPath = QLabel(tr("Nenhuma pasta selecionada", "No folder selected"))
        self.pcaLayout.addWidget(self.exportPath)

        self.exportButton = QPushButton(tr("Exportar relatório completo (CSV)",
                                           "Export full report (CSV)"))
        self.pcaLayout.addWidget(self.exportButton)

        # ---- NOVO: Exportar PCs como raster ----
        self.pcaExportGroup = QGroupBox(tr("Exportar PCs como raster", "Export PCs as raster"))
        _pcaExpLay = QHBoxLayout(self.pcaExportGroup)

        self.pcExportLabel = QLabel(tr("Escolha a PC:", "Choose PC:"))
        _pcaExpLay.addWidget(self.pcExportLabel)

        self.pcExportCombo = QComboBox()
        _pcaExpLay.addWidget(self.pcExportCombo)

        self.btnExportPCRaster = QPushButton(tr("Exportar PC selecionada (GeoTIFF)", "Export selected PC (GeoTIFF)"))
        _pcaExpLay.addWidget(self.btnExportPCRaster)

        self.btnExportAllPCRasters = QPushButton(tr("Exportar todas as PCs (multi-banda)", "Export all PCs (multi-band)"))
        _pcaExpLay.addWidget(self.btnExportAllPCRasters)

        self.pcaLayout.addWidget(self.pcaExportGroup)

        # Conexões dos botões novos
        self.btnExportPCRaster.clicked.connect(self._export_selected_pc_as_raster)
        self.btnExportAllPCRasters.clicked.connect(self._export_all_pcs_as_multiband)

        # ===================== Aba Zonas =====================
        self.zonasTab = QWidget()
        self.tabs.addTab(self.zonasTab, tr("Zonas", "Zones"))

        self.zonasLayout = QVBoxLayout(self.zonasTab)

        # Fonte dos dados para clusterização (PCA vs Originais)
        self.grpFonte = QGroupBox(tr("Fonte dos dados para clusterização",
                                     "Data source for clustering"))
        self.radPCA   = QRadioButton(tr("PCA (componentes selecionadas)",
                                        "PCA (selected components)"))
        self.radOrig  = QRadioButton(tr("Variáveis originais (z-score)",
                                        "Original variables (z-score)"))
        self.radPCA.setChecked(True)
        _gLay = QVBoxLayout(self.grpFonte)
        _gLay.addWidget(self.radPCA)
        _gLay.addWidget(self.radOrig)
        self.zonasLayout.addWidget(self.grpFonte)

        # Seleção de PCs
        self.pcSelectorLayout = QHBoxLayout()
        self.zonasLayout.addLayout(self.pcSelectorLayout)

        self.pcSelectorLabel = QLabel(tr("Número de PCs a usar:", "Number of PCs to use:"))
        self.pcSelectorLayout.addWidget(self.pcSelectorLabel)

        self.pcSelector = QComboBox()
        self.pcSelectorLayout.addWidget(self.pcSelector)
        self.radPCA.toggled.connect(self._toggle_pc_selector)
        self._toggle_pc_selector(self.radPCA.isChecked())

        # Range de clusters (Elbow)
        self.clusterRangeLayout = QHBoxLayout()
        self.zonasLayout.addLayout(self.clusterRangeLayout)

        self.clusterMinLabel = QLabel(tr("Clusters mínimos:", "Min clusters:"))
        self.clusterRangeLayout.addWidget(self.clusterMinLabel)

        self.clusterMinSpin = QSpinBox()
        self.clusterMinSpin.setMinimum(2)
        self.clusterMinSpin.setMaximum(20)
        self.clusterMinSpin.setValue(2)
        self.clusterRangeLayout.addWidget(self.clusterMinSpin)

        self.clusterMaxLabel = QLabel(tr("Clusters máximos:", "Max clusters:"))
        self.clusterRangeLayout.addWidget(self.clusterMaxLabel)

        self.clusterMaxSpin = QSpinBox()
        self.clusterMaxSpin.setMinimum(2)
        self.clusterMaxSpin.setMaximum(20)
        self.clusterMaxSpin.setValue(10)
        self.clusterRangeLayout.addWidget(self.clusterMaxSpin)

        self.executarZonasButton = QPushButton(tr(
            "Executar análise de zonas (KMeans + Elbow)",
            "Run zones analysis (KMeans + Elbow)"
        ))
        self.zonasLayout.addWidget(self.executarZonasButton)

        self.indicesTable = QTableWidget()
        self.indicesTable.setColumnCount(2)
        self.indicesTable.setHorizontalHeaderLabels([tr("Clusters", "Clusters"),
                                                     tr("Inércia", "Inertia")])
        self.zonasLayout.addWidget(self.indicesTable)

        self.elbowCanvas = FigureCanvas(Figure(figsize=(4, 2)))
        self.zonasLayout.addWidget(self.elbowCanvas)
        self.elbowAxes = self.elbowCanvas.figure.add_subplot(111)

        self.exportElbowButton = QPushButton(tr("Exportar gráfico Elbow (PNG)",
                                                "Export Elbow plot (PNG)"))
        self.zonasLayout.addWidget(self.exportElbowButton)

        self.exportZonasButton = QPushButton(tr("Exportar resultados (CSV)",
                                                "Export results (CSV)"))
        self.zonasLayout.addWidget(self.exportZonasButton)

        # Geração final (k escolhido)
        self.finalClusterLayout = QHBoxLayout()
        self.zonasLayout.addLayout(self.finalClusterLayout)

        self.finalClusterLabel = QLabel(tr("Número de zonas para gerar (KMeans):",
                                           "Number of zones to generate (KMeans):"))
        self.finalClusterLayout.addWidget(self.finalClusterLabel)

        self.finalClusterSpin = QSpinBox()
        self.finalClusterSpin.setMinimum(2)
        self.finalClusterSpin.setMaximum(20)
        self.finalClusterSpin.setValue(3)
        self.finalClusterLayout.addWidget(self.finalClusterSpin)

        self.gerarZonasButton = QPushButton(tr("Gerar zonas de manejo (como raster)",
                                               "Generate management zones (as raster)"))
        self.zonasLayout.addWidget(self.gerarZonasButton)

        # ===================== Aba Filtro Modal =====================
        self.filtroTab = QWidget()
        self.tabs.addTab(self.filtroTab, tr("Filtro Modal", "Mode Filter"))

        self.filtroLayout = QVBoxLayout(self.filtroTab)

        self.filtroLayout.addWidget(QLabel(tr("Raster de entrada (Zonas):",
                                              "Input raster (Zones):")))
        self.rasterFiltroCombo = QComboBox()
        self.filtroLayout.addWidget(self.rasterFiltroCombo)

        self.filtroLayout.addWidget(QLabel(tr("Tamanho da janela (ex: 3, 5, 7):",
                                              "Window size (e.g., 3, 5, 7):")))
        self.windowSizeSpin = QSpinBox()
        self.windowSizeSpin.setMinimum(3)
        self.windowSizeSpin.setMaximum(99)
        self.windowSizeSpin.setSingleStep(2)
        self.windowSizeSpin.setValue(5)
        self.filtroLayout.addWidget(self.windowSizeSpin)
        self.filtroLayout.addWidget(QLabel(tr(
            "Tamanho de janela: 3 = 7x7 pixels, 5 = 11x11 pixels, etc.",
            "Window size: 3 = 7x7 pixels, 5 = 11x11 pixels, etc."
        )))

        self.executarFiltroButton = QPushButton(tr("Executar Filtro Modal", "Run Mode Filter"))
        self.filtroLayout.addWidget(self.executarFiltroButton)

        # ===================== Aba Análises =====================
        self.analisesTab = QWidget()
        self.tabs.addTab(self.analisesTab, tr("Análises", "Analyses"))

        self.analisesLayout = QVBoxLayout(self.analisesTab)

        # Escolha do raster de zonas
        self.analisesLayout.addWidget(QLabel(tr("Raster de Zonas (já no QGIS):",
                                                "Zones raster (already in QGIS):")))
        self.zonasRasterCombo = QComboBox()
        self.analisesLayout.addWidget(self.zonasRasterCombo)

        # Resultado VR + tabela (mostrados após rodar a análise)
        self.resultadoVRLabel = QLabel("VR: -")
        self.analisesLayout.addWidget(self.resultadoVRLabel)

        self.resultadoTabela = QTableWidget()
        self.resultadoTabela.setColumnCount(5)
        self.resultadoTabela.setHorizontalHeaderLabels([
            tr("Zona", "Zone"),
            tr("Média", "Mean"),
            tr("Variância", "Variance"),
            "n",
            tr("Área (ha)", "Area (ha)")
        ])
        self.analisesLayout.addWidget(self.resultadoTabela)

        # CSV externo (opcional)
        self.analisesLayout.addWidget(QLabel(tr("Ou carregar CSV com dados externos:",
                                                "Or load CSV with external data:")))
        self.botaoCarregarCSV = QPushButton(tr("Carregar CSV de pontos", "Load points CSV"))
        self.analisesLayout.addWidget(self.botaoCarregarCSV)

        # Seleção das colunas do CSV
        self.analisesLayout.addWidget(QLabel(tr("Coluna X (longitude):", "X column (longitude):")))
        self.colunaXCombo = QComboBox()
        self.analisesLayout.addWidget(self.colunaXCombo)

        self.analisesLayout.addWidget(QLabel(tr("Coluna Y (latitude):", "Y column (latitude):")))
        self.colunaYCombo = QComboBox()
        self.analisesLayout.addWidget(self.colunaYCombo)

        self.analisesLayout.addWidget(QLabel(tr("Coluna do atributo:", "Attribute column:")))
        self.colunaAtributoCombo = QComboBox()
        self.analisesLayout.addWidget(self.colunaAtributoCombo)

        # >>> Botão da análise
        self.executarAnaliseButton = QPushButton(tr("Executar Redução de Variância",
                                                    "Run Variance Reduction"))
        self.analisesLayout.addWidget(self.executarAnaliseButton)

        # Exportar boxplots
        self.exportarBoxplotsButton = QPushButton(tr("Exportar boxplots (PNG)", "Export boxplots (PNG)"))
        self.analisesLayout.addWidget(self.exportarBoxplotsButton)

        # Atualiza combos quando muda de aba Filtro/Análises
        self.tabs.currentChanged.connect(self.atualizar_combo_se_necessario)

    # ===================== Funções auxiliares =====================
    def _show_deps_help(self):
        dlg = _DepsHelpDialog(self)
        dlg.exec_()

    def _check_deps(self):
        # pandas
        self.chkPandas.setChecked(self._try_import("pandas"))
        # scikit-learn (KMeans está dentro de sklearn)
        self.chkSklearn.setChecked(self._try_import("sklearn.cluster"))
        # SAGA provider (NextGen preferencial; aceita 'sagang' ou, se não, 'saga')
        reg = QgsApplication.processingRegistry()
        has_sagang = reg.providerById("sagang") is not None
        has_saga   = reg.providerById("saga")   is not None
        self.chkSaga.setChecked(bool(has_sagang or has_saga))

    def _try_import(self, module_name: str) -> bool:
        try:
            __import__(module_name)
            return True
        except Exception:
            return False

    def atualizar_lista_rasters(self):
        self.rasterFiltroCombo.clear()
        self.zonasRasterCombo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer):
                self.rasterFiltroCombo.addItem(layer.name())
                self.zonasRasterCombo.addItem(layer.name())

    def atualizar_combo_se_necessario(self, index):
        aba_filtro_index = self.tabs.indexOf(self.filtroTab)
        aba_analises_index = self.tabs.indexOf(self.analisesTab)
        if index == aba_filtro_index or index == aba_analises_index:
            self.atualizar_lista_rasters()

    def _toggle_pc_selector(self, pca_ativo: bool):
        self.pcSelector.setEnabled(pca_ativo)
        self.pcSelectorLabel.setEnabled(pca_ativo)

    def atualizar_combo_atributos(self):
        # Mantido como placeholder caso precise no futuro
        pass

    # ======== NOVO: utilidades para exportação das PCs ========
    def popular_combo_pcs(self, n_components: int):
        """Preenche os combos de PCs das abas PCA/Zonas."""
        try:
            self.pcExportCombo.clear()
            self.pcSelector.clear()
            for i in range(n_components):
                self.pcExportCombo.addItem(f"PC{i+1}", i)  # dado = índice 0-based
                self.pcSelector.addItem(str(i+1))
        except Exception:
            pass

    def _fetch_parent_attr(self, name, default=None):
        """
        Busca atributos primeiro em self._plugin (se o plugin tiver injetado: dialog._plugin = plugin),
        depois tenta no parent() (caso o parent seja um QWidget com esses atributos).
        """
        p = getattr(self, "_plugin", None)
        if p is not None and hasattr(p, name):
            return getattr(p, name, default)
        par = self.parent()
        return getattr(par, name, default) if par is not None else default

    def _ensure_ref_metadata(self):
        """
        Garante self.ref_gt, self.ref_crs_wkt e self.grid_shape.
        1) tenta pegar do plugin (via _plugin) / parent();
        2) se não houver, tenta inferir do primeiro raster selecionado na aba Reamostragem.
        """
        if self.ref_gt is not None and self.grid_shape is not None and self.ref_crs_wkt is not None:
            return True

        # 1) do plugin/parent
        gt  = self._fetch_parent_attr("ref_gt", None)
        wkt = self._fetch_parent_attr("ref_crs_wkt", None)
        shape = self._fetch_parent_attr("grid_shape", None)
        if gt is not None and wkt is not None and shape is not None:
            self.ref_gt = gt
            self.ref_crs_wkt = wkt
            self.grid_shape = shape
            return True

        # 2) inferir do primeiro raster selecionado
        try:
            sel = self.rasterListWidget.selectedItems()
            if not sel:
                # tenta do combo filtro/analises (qualquer um)
                name = self.rasterFiltroCombo.currentText() or self.zonasRasterCombo.currentText()
            else:
                name = sel[0].text()
            if not name:
                return False
            # localizar layer
            ref_layer = None
            for lyr in QgsProject.instance().mapLayers().values():
                if isinstance(lyr, QgsRasterLayer) and lyr.name() == name:
                    ref_layer = lyr
                    break
            if ref_layer is None or not ref_layer.isValid():
                return False

            ref_path = ref_layer.dataProvider().dataSourceUri().split("|")[0]
            ds = gdal.Open(ref_path)
            if ds is None:
                return False
            self.ref_gt = ds.GetGeoTransform()
            self.ref_crs_wkt = ds.GetProjection()
            self.grid_shape = (ds.RasterYSize, ds.RasterXSize)
            return True
        except Exception:
            return False

    def _xy_to_rowcol(self, x: float, y: float):
        """Converte coordenadas (X,Y) para índices (row, col) usando self.ref_gt."""
        gt = self.ref_gt
        if gt is None:
            return None
        try:
            col = int((x - gt[0]) / gt[1])
            row = int((y - gt[3]) / gt[5])  # gt[5] costuma ser negativo
            return (row, col)
        except Exception:
            return None

    def _write_geotiff_from_array(self, array2d: np.ndarray,
                                  geotransform: tuple,
                                  crs_wkt: str,
                                  out_path: str,
                                  nodata_value: float = -9999.0):
        """Escreve um GeoTIFF Float32 a partir de um array 2D e metadados da raster de referência."""
        rows, cols = array2d.shape
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(out_path, cols, rows, 1, gdal.GDT_Float32, options=["COMPRESS=LZW", "TILED=YES"])
        if ds is None:
            raise RuntimeError(tr("Não foi possível criar o GeoTIFF de saída.",
                                  "Could not create output GeoTIFF."))
        ds.SetGeoTransform(geotransform)

        if crs_wkt:
            srs = osr.SpatialReference()
            srs.ImportFromWkt(crs_wkt)
            ds.SetProjection(srs.ExportToWkt())

        band = ds.GetRasterBand(1)
        band.WriteArray(array2d)
        band.SetNoDataValue(nodata_value)
        band.FlushCache()

        ds.FlushCache()
        ds = None  # fecha

    # ======== NOVO: ações dos botões de exportação ========
    def _resolve_pca_scores(self):
        """
        Retorna (scores, n_components) buscando, nesta ordem:
        - self._plugin.pca_scores;
        - self._plugin.pca_transformada;
        - parent().pca_scores/transformada;
        - None se não houver.
        """
        scores = self._fetch_parent_attr("pca_scores", None)
        if scores is None:
            scores = self._fetch_parent_attr("pca_transformada", None)
        if scores is None:
            return None, 0
        return scores, scores.shape[1] if hasattr(scores, "shape") and len(scores.shape) == 2 else 0

    def _resolve_points_df(self):
        """
        Tenta obter o DataFrame de pontos (com colunas X,Y) do plugin/parent: dados_amostrados.
        Retorna o DF ou None.
        """
        return self._fetch_parent_attr("dados_amostrados", None)

    def _maybe_autofill_pc_combo(self):
        """Se o combo de PCs estiver vazio, tenta popular usando os scores do plugin/parent."""
        if self.pcExportCombo.count() > 0 and self.pcSelector.count() > 0:
            return
        scores, ncomp = self._resolve_pca_scores()
        if scores is not None and ncomp > 0:
            self.popular_combo_pcs(ncomp)

    def _export_selected_pc_as_raster(self):
        try:
            # Garante metadados de referência
            if not self._ensure_ref_metadata():
                QMessageBox.warning(self, tr("Erro", "Error"),
                                    tr("Metadados do raster de referência ausentes. "
                                       "Selecione um raster na aba Reamostragem (ou execute a etapa).",
                                       "Reference raster metadata missing. "
                                       "Select a raster in the Resampling tab (or run that step)."))
                return

            # Garante que o combo tem PCs
            self._maybe_autofill_pc_combo()

            # Determina índice da PC
            pc_idx = self.pcExportCombo.currentData()
            if pc_idx is None:
                txt = self.pcExportCombo.currentText().strip().upper()
                if txt.startswith("PC"):
                    try:
                        pc_idx = int(txt.replace("PC", "")) - 1
                    except Exception:
                        pc_idx = None
            if pc_idx is None or pc_idx < 0:
                QMessageBox.warning(self, tr("Atenção", "Warning"),
                                    tr("Nenhuma PC selecionada.", "No PC selected."))
                return

            # Obtém scores e DF de pontos
            scores, ncomp = self._resolve_pca_scores()
            if scores is None or ncomp == 0:
                QMessageBox.warning(self, tr("Erro", "Error"),
                                    tr("Execute a PCA no plugin antes de exportar.",
                                       "Run PCA in the plugin before exporting."))
                return
            if pc_idx >= ncomp:
                QMessageBox.warning(self, tr("Atenção", "Warning"),
                                    tr("Índice de PC inválido.", "Invalid PC index."))
                return

            df = self._resolve_points_df()
            if df is None or df.empty or not all(k in df.columns for k in ("X", "Y")):
                QMessageBox.warning(self, tr("Erro", "Error"),
                                    tr("Pontos (X,Y) não encontrados. Execute a reamostragem no plugin.",
                                       "Points (X,Y) not found. Run resampling in the plugin."))
                return

            # Arquivo de saída
            sugestao = f"PC{pc_idx+1}.tif"
            out_path, _ = QFileDialog.getSaveFileName(
                self,
                tr("Salvar GeoTIFF da PC", "Save PC GeoTIFF"),
                sugestao,
                tr("GeoTIFF (*.tif)", "GeoTIFF (*.tif)")
            )
            if not out_path:
                return
            if not out_path.lower().endswith(".tif"):
                out_path += ".tif"

            # Monta raster
            rows, cols = self.grid_shape
            nodata_value = -9999.0
            arr = np.full((rows, cols), nodata_value, dtype=np.float32)

            # Segurança quanto ao tamanho
            min_n = min(len(df), scores.shape[0])
            vals = scores[:min_n, pc_idx].astype(np.float32)

            for i, (x, y) in enumerate(df.loc[:min_n-1, ["X", "Y"]].itertuples(index=False, name=None)):
                rc = self._xy_to_rowcol(float(x), float(y))
                if rc is None:
                    continue
                r, c = rc
                if 0 <= r < rows and 0 <= c < cols:
                    arr[r, c] = vals[i]

            # Grava GeoTIFF
            self._write_geotiff_from_array(arr, self.ref_gt, self.ref_crs_wkt, out_path, nodata_value=nodata_value)

            QMessageBox.information(self, tr("Concluído", "Done"),
                                    tr("Raster da PC exportado com sucesso.",
                                       "PC raster exported successfully."))
        except Exception as e:
            QMessageBox.critical(self, tr("Erro ao exportar", "Export error"), str(e))

    def _export_all_pcs_as_multiband(self):
        try:
            # Garante metadados de referência
            if not self._ensure_ref_metadata():
                QMessageBox.warning(self, tr("Erro", "Error"),
                                    tr("Metadados do raster de referência ausentes. "
                                       "Selecione um raster na aba Reamostragem (ou execute a etapa).",
                                       "Reference raster metadata missing. "
                                       "Select a raster in the Resampling tab (or run that step)."))
                return

            scores, ncomp = self._resolve_pca_scores()
            if scores is None or ncomp == 0:
                QMessageBox.warning(self, tr("Erro", "Error"),
                                    tr("Execute a PCA no plugin antes de exportar.",
                                       "Run PCA in the plugin before exporting."))
                return

            df = self._resolve_points_df()
            if df is None or df.empty or not all(k in df.columns for k in ("X", "Y")):
                QMessageBox.warning(self, tr("Erro", "Error"),
                                    tr("Pontos (X,Y) não encontrados. Execute a reamostragem no plugin.",
                                       "Points (X,Y) not found. Run resampling in the plugin."))
                return

            out_path, _ = QFileDialog.getSaveFileName(
                self,
                tr("Salvar PCs (multibanda)", "Save PCs (multiband)"),
                "PCs.tif",
                tr("GeoTIFF (*.tif)", "GeoTIFF (*.tif)")
            )
            if not out_path:
                return
            if not out_path.lower().endswith(".tif"):
                out_path += ".tif"

            rows, cols = self.grid_shape
            nb = ncomp
            nodata_value = -9999.0

            driver = gdal.GetDriverByName("GTiff")
            ds = driver.Create(out_path, cols, rows, nb, gdal.GDT_Float32, options=["COMPRESS=LZW", "TILED=YES"])
            if ds is None:
                raise RuntimeError(tr("Falha ao criar GeoTIFF multibanda.", "Failed to create multiband GeoTIFF."))

            # GeoTransform/Proj
            ds.SetGeoTransform(self.ref_gt)
            if self.ref_crs_wkt:
                srs = osr.SpatialReference()
                srs.ImportFromWkt(self.ref_crs_wkt)
                ds.SetProjection(srs.ExportToWkt())

            min_n = min(len(df), scores.shape[0])

            for b in range(nb):
                band_arr = np.full((rows, cols), nodata_value, dtype=np.float32)
                vals = scores[:min_n, b].astype(np.float32)
                for i, (x, y) in enumerate(df.loc[:min_n-1, ["X", "Y"]].itertuples(index=False, name=None)):
                    rc = self._xy_to_rowcol(float(x), float(y))
                    if rc is None:
                        continue
                    r, c = rc
                    if 0 <= r < rows and 0 <= c < cols:
                        band_arr[r, c] = vals[i]

                rb = ds.GetRasterBand(b + 1)
                rb.WriteArray(band_arr)
                rb.SetNoDataValue(nodata_value)
                rb.SetDescription(f"PC{b+1}")
                rb.FlushCache()

            ds.FlushCache()
            ds = None

            QMessageBox.information(self, tr("Concluído", "Done"),
                                    tr("GeoTIFF multibanda das PCs exportado com sucesso.",
                                       "Multiband PCs GeoTIFF exported successfully."))
        except Exception as e:
            QMessageBox.critical(self, tr("Erro ao exportar", "Export error"), str(e))
