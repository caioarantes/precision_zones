# -*- coding: utf-8 -*-
"""Precision Zones - main dialog (pure UI / view).

PyQt5/PyQt6 compatible via qgis.PyQt. Holds only widget construction and simple
widget-update helpers. All backend work lives in services/, orchestrated by the
controllers/ which connect to this dialog's widgets.
"""
from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QListWidget, QLineEdit, QTableWidget, QWidget, QSpinBox,
    QGroupBox, QRadioButton
)

from qgis.core import QgsProject, QgsRasterLayer

# Matplotlib canvas: Qt6 uses qtagg; Qt5 uses qt5agg
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except Exception:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from ..core.i18n import tr
from ..core.qt_compat import set_multiselection


class PrecisionZonesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Nome próprio do plugin: fixo em inglês
        self.setWindowTitle("Precision Zones")
        self.resize(600, 520)

        # Reference to the shared PZSession; injected by the plugin entry.
        self.session = None

        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ===================== Aba Reamostragem =====================
        self.mainTab = QWidget()
        self.tabs.addTab(self.mainTab, tr("Reamostragem", "Resampling"))
        self.mainLayout = QVBoxLayout(self.mainTab)

        self.mainLayout.addWidget(QLabel(tr("Camada Vetorial - UTM (contorno):",
                                            "Vector layer - UTM (boundary):")))
        self.vectorLayerCombo = QComboBox()
        self.mainLayout.addWidget(self.vectorLayerCombo)

        self.mainLayout.addWidget(QLabel(tr("Rasters disponíveis:", "Available rasters:")))
        self.rasterListWidget = QListWidget()
        set_multiselection(self.rasterListWidget)
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
        self.pcaTable.setColumnCount(4)
        self.pcaTable.setHorizontalHeaderLabels([
            tr("Componente", "Component"),
            tr("Autovalor (λ)", "Eigenvalue (λ)"),
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

        # ---- Exportar PCs como raster ----
        self.pcaExportGroup = QGroupBox(tr("Exportar PCs como raster", "Export PCs as raster"))
        _pcaExpLay = QHBoxLayout(self.pcaExportGroup)

        self.pcExportLabel = QLabel(tr("Escolha a PC:", "Choose PC:"))
        _pcaExpLay.addWidget(self.pcExportLabel)

        self.pcExportCombo = QComboBox()
        self.pcExportCombo.setEnabled(False)  # habilita após PCA
        _pcaExpLay.addWidget(self.pcExportCombo)

        self.btnExportPCRaster = QPushButton(tr("Exportar PC selecionada (GeoTIFF)", "Export selected PC (GeoTIFF)"))
        _pcaExpLay.addWidget(self.btnExportPCRaster)

        self.btnExportAllPCRasters = QPushButton(tr("Exportar todas as PCs (multi-banda)", "Export all PCs (multi-band)"))
        _pcaExpLay.addWidget(self.btnExportAllPCRasters)

        self.pcaLayout.addWidget(self.pcaExportGroup)

        # ===================== Aba Zonas =====================
        self.zonasTab = QWidget()
        self.tabs.addTab(self.zonasTab, tr("Zonas", "Zones"))
        self.zonasLayout = QVBoxLayout(self.zonasTab)

        self.grpFonte = QGroupBox(tr("Fonte dos dados para clusterização",
                                     "Data source for clustering"))
        self.radPCA = QRadioButton(tr("PCA (componentes selecionadas)",
                                      "PCA (selected components)"))
        self.radOrig = QRadioButton(tr("Variáveis originais (z-score)",
                                       "Original variables (z-score)"))
        self.radPCA.setChecked(True)
        _gLay = QVBoxLayout(self.grpFonte)
        _gLay.addWidget(self.radPCA)
        _gLay.addWidget(self.radOrig)
        self.zonasLayout.addWidget(self.grpFonte)

        self.pcSelectorLayout = QHBoxLayout()
        self.zonasLayout.addLayout(self.pcSelectorLayout)

        self.pcSelectorLabel = QLabel(tr("Número de PCs a usar:", "Number of PCs to use:"))
        self.pcSelectorLayout.addWidget(self.pcSelectorLabel)

        self.pcSelector = QComboBox()
        self.pcSelectorLayout.addWidget(self.pcSelector)

        self.radPCA.toggled.connect(self._toggle_pc_selector)
        self._toggle_pc_selector(self.radPCA.isChecked())

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
            "Executar análise de zonas (KMeans + Elbow + Silhueta)",
            "Run zones analysis (KMeans + Elbow + Silhouette)"
        ))
        self.zonasLayout.addWidget(self.executarZonasButton)

        self.indicesTable = QTableWidget()
        self.indicesTable.setColumnCount(3)
        self.indicesTable.setHorizontalHeaderLabels([
            tr("Clusters", "Clusters"),
            tr("Inércia", "Inertia"),
            tr("Silhueta", "Silhouette")
        ])
        self.zonasLayout.addWidget(self.indicesTable)

        self.elbowCanvas = FigureCanvas(Figure(figsize=(4, 2)))
        self.zonasLayout.addWidget(self.elbowCanvas)
        self.elbowAxes = self.elbowCanvas.figure.add_subplot(111)

        self.exportElbowButton = QPushButton(tr("Exportar gráfico (Elbow + Silhueta) [PNG]",
                                                "Export plot (Elbow + Silhouette) [PNG]"))
        self.zonasLayout.addWidget(self.exportElbowButton)

        self.exportZonasButton = QPushButton(tr("Exportar resultados (Elbow + Silhueta) [CSV]",
                                                "Export results (Elbow + Silhouette) [CSV]"))
        self.zonasLayout.addWidget(self.exportZonasButton)

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
        self.tabs.addTab(self.analisesTab, tr("Análises", "Analysis"))
        self.analisesLayout = QVBoxLayout(self.analisesTab)

        self.analisesLayout.addWidget(QLabel(tr("Raster de Zonas (já no QGIS):",
                                                "Zones raster (already in QGIS):")))
        self.zonasRasterCombo = QComboBox()
        self.analisesLayout.addWidget(self.zonasRasterCombo)

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

        self.analisesLayout.addWidget(QLabel(tr("Ou carregar CSV com dados externos:",
                                                "Or load CSV with external data:")))
        self.botaoCarregarCSV = QPushButton(tr("Carregar CSV de pontos", "Load points CSV"))
        self.analisesLayout.addWidget(self.botaoCarregarCSV)

        self.analisesLayout.addWidget(QLabel(tr("Coluna X (longitude):", "X column (longitude):")))
        self.colunaXCombo = QComboBox()
        self.analisesLayout.addWidget(self.colunaXCombo)

        self.analisesLayout.addWidget(QLabel(tr("Coluna Y (latitude):", "Y column (latitude):")))
        self.colunaYCombo = QComboBox()
        self.analisesLayout.addWidget(self.colunaYCombo)

        self.analisesLayout.addWidget(QLabel(tr("Coluna do atributo:", "Attribute column:")))
        self.colunaAtributoCombo = QComboBox()
        self.analisesLayout.addWidget(self.colunaAtributoCombo)

        self.executarAnaliseButton = QPushButton(tr("Executar Redução de Variância",
                                                    "Run Variance Reduction"))
        self.analisesLayout.addWidget(self.executarAnaliseButton)

        self.exportarBoxplotsButton = QPushButton(tr("Exportar boxplots (PNG)", "Export boxplots (PNG)"))
        self.analisesLayout.addWidget(self.exportarBoxplotsButton)

        # Atualiza combos quando muda de aba Filtro/Análises
        self.tabs.currentChanged.connect(self.atualizar_combo_se_necessario)

        # Atualize combos ao iniciar
        try:
            self.atualizar_lista_rasters()
        except Exception:
            pass

    # ===================== UI update helpers =====================
    def atualizar_lista_rasters(self):
        self.rasterFiltroCombo.clear()
        self.zonasRasterCombo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer):
                self.rasterFiltroCombo.addItem(layer.name())
                self.zonasRasterCombo.addItem(layer.name())

    def atualizar_combo_se_necessario(self, index: int):
        aba_filtro_index = self.tabs.indexOf(self.filtroTab)
        aba_analises_index = self.tabs.indexOf(self.analisesTab)
        if index == aba_filtro_index or index == aba_analises_index:
            self.atualizar_lista_rasters()

    def _toggle_pc_selector(self, pca_ativo: bool):
        self.pcSelector.setEnabled(bool(pca_ativo))
        self.pcSelectorLabel.setEnabled(bool(pca_ativo))

    def atualizar_combo_atributos(self):
        # Mantido como placeholder caso precise no futuro
        pass

    def popular_combo_pcs(self, n_components: int):
        """Preenche pcExportCombo (PCA) e pcSelector (Zonas) após a PCA."""
        try:
            self.pcExportCombo.clear()
            for i in range(n_components):
                self.pcExportCombo.addItem(f"PC{i+1}", i)  # data = índice 0-based
            self.pcExportCombo.setEnabled(self.pcExportCombo.count() > 0)
            if self.pcExportCombo.count() > 0:
                self.pcExportCombo.setCurrentIndex(0)

            self.pcSelector.clear()
            for i in range(1, n_components + 1):
                self.pcSelector.addItem(str(i))
            self._toggle_pc_selector(self.radPCA.isChecked())
            if self.pcSelector.count() > 0:
                self.pcSelector.setCurrentIndex(0)
        except Exception:
            pass
