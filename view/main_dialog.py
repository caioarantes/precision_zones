# -*- coding: utf-8 -*-
"""Precision Zones - main dialog (pure UI / view).

AGLgis-style shell: a fixed header (brand | page title | help), a hover-expand
navigation sidebar, and a QStackedWidget of pages. Holds only widget construction
and simple update helpers; all backend work lives in services/, orchestrated by
controllers/ which connect to this dialog's widgets by name.
"""
import os

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QLineEdit, QTableWidget, QWidget, QSpinBox, QGroupBox,
    QRadioButton, QStackedWidget, QScrollArea, QFrame, QTextBrowser,
)

from qgis.core import QgsProject, QgsRasterLayer

# Matplotlib canvas: Qt6 uses qtagg; Qt5 uses qt5agg
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except Exception:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from ..core.i18n import tr, qgis_locale_lang
from ..core.qt_compat import set_multiselection
from .sidebar import Sidebar, PAGES
from .styles import (
    STYLE_DIALOG, STYLE_PAGE, STYLE_BTN_PRIMARY, STYLE_BTN_SECONDARY, STYLE_BTN_HELP,
)

HELP_URL = "https://github.com/Derleimelo/Precision-Zones-Plugin"

_PAGE_TITLES = {
    "intro": tr("Introduction"),
    "resample": tr("Resampling"),
    "pca": "PCA",
    "zones": tr("Zones"),
    "filter": tr("Mode Filter"),
    "analysis": tr("Analysis"),
}

ORDER = [key for key, _ in PAGES]


class PrecisionZonesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Precision Zones")
        self.setMinimumSize(760, 520)
        self.resize(840, 600)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(STYLE_DIALOG)

        # Reference to the shared PZSession; injected by the plugin entry.
        self.session = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.page_requested.connect(self._go_to_page)
        body_lay.addWidget(self.sidebar)

        right_col = QWidget()
        right_lay = QVBoxLayout(right_col)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setFrameShape(QFrame.Shape.NoFrame)
        right_lay.addWidget(self.stack, 1)
        right_lay.addWidget(self._build_navbar())
        body_lay.addWidget(right_col, 1)

        builders = {
            "intro": self._build_intro_page,
            "resample": self._build_resample_page,
            "pca": self._build_pca_page,
            "zones": self._build_zones_page,
            "filter": self._build_filter_page,
            "analysis": self._build_analysis_page,
        }
        self.pages = {}
        for key, _label in PAGES:
            inner = builders[key]()
            scroll = self._wrap_scroll(inner)
            self.pages[key] = scroll
            self.stack.addWidget(scroll)

        self.stack.currentChanged.connect(self._sync_page_state)
        self.stack.setCurrentWidget(self.pages["intro"])
        self._sync_page_state(self.stack.currentIndex())

        root.addWidget(body, 1)

    # ------------------------------------------------------------ shell
    def _build_header(self):
        header = QWidget()
        header.setFixedHeight(40)
        header.setStyleSheet("background-color: #ffffff; border-bottom: 1px solid #e0e0e0;")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(0)

        brand = QLabel("Precision Zones")
        brand.setStyleSheet("color: #37474F; font-size: 13px; font-weight: bold; letter-spacing: 0.5px;")
        lay.addWidget(brand)

        sep = QLabel("  |")
        sep.setStyleSheet("color: #d0d0d0; font-size: 16px;")
        lay.addWidget(sep)

        self._page_title = QLabel(_PAGE_TITLES["intro"])
        self._page_title.setStyleSheet("color: #616161; font-size: 13px; margin-left: 6px;")
        lay.addWidget(self._page_title)

        lay.addStretch()

        self.helpButton = QPushButton("?")
        self.helpButton.setFixedSize(28, 28)
        self.helpButton.setToolTip(tr("Learn more"))
        self.helpButton.setStyleSheet(STYLE_BTN_HELP)
        self.helpButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.helpButton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(HELP_URL)))
        lay.addWidget(self.helpButton)
        return header

    def _wrap_scroll(self, inner):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    def _new_page(self):
        """Return (page, card_layout): a styled page with a white card to fill."""
        page = QWidget()
        page.setObjectName("pzPage")
        page.setStyleSheet(STYLE_PAGE)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(0)
        panel = QFrame()
        panel.setObjectName("pzPanel")
        card = QVBoxLayout(panel)
        card.setContentsMargins(18, 18, 18, 18)
        card.setSpacing(8)
        outer.addWidget(panel)
        outer.addStretch()
        return page, card

    @staticmethod
    def _primary(btn):
        btn.setStyleSheet(STYLE_BTN_PRIMARY)
        btn.setMinimumHeight(34)
        return btn

    @staticmethod
    def _secondary(btn):
        btn.setStyleSheet(STYLE_BTN_SECONDARY)
        btn.setMinimumHeight(30)
        return btn

    @staticmethod
    def _field(text):
        """A small, styled field caption (clearer hierarchy than a plain label)."""
        lbl = QLabel(text)
        lbl.setObjectName("pzFieldLabel")
        return lbl

    @staticmethod
    def _hint(text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        lbl.setWordWrap(True)
        return lbl

    def _build_navbar(self):
        """Persistent Back / step / Next bar, fixed below the page stack."""
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background-color: #ffffff; border-top: 1px solid #e0e0e0;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 8, 18, 8)

        self._navBack = self._secondary(QPushButton(tr("← Back")))
        self._navBack.clicked.connect(self._nav_back)
        lay.addWidget(self._navBack)

        lay.addStretch()
        self._navStep = QLabel("")
        self._navStep.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        lay.addWidget(self._navStep)
        lay.addStretch()

        self._navNext = self._secondary(QPushButton(tr("Next →")))
        self._navNext.clicked.connect(self._nav_next)
        lay.addWidget(self._navNext)
        return bar

    def _current_index(self):
        widget = self.stack.currentWidget()
        for k, w in self.pages.items():
            if w is widget:
                return ORDER.index(k)
        return 0

    def _go_to_index(self, i):
        if 0 <= i < len(ORDER):
            self._go_to_page(ORDER[i])

    def _nav_back(self):
        self._go_to_index(self._current_index() - 1)

    def _nav_next(self):
        self._go_to_index(self._current_index() + 1)

    # ------------------------------------------------------------ pages
    def _build_intro_page(self):
        page = QWidget()
        page.setObjectName("pzPage")
        page.setStyleSheet(STYLE_PAGE)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 18, 18, 18)
        browser = QTextBrowser()
        browser.setObjectName("pzPanel")
        browser.setOpenExternalLinks(True)
        plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        intro_path = os.path.join(plugin_dir, "intro.html")
        if qgis_locale_lang() == "pt":
            pt = os.path.join(plugin_dir, "intro_pt_br.html")
            if os.path.exists(pt):
                intro_path = pt
        try:
            with open(intro_path, "r", encoding="utf-8") as f:
                browser.setHtml(f.read())
        except Exception:
            browser.setHtml("<h1>Precision Zones</h1>")
        outer.addWidget(browser)
        self.introBrowser = browser
        return page

    def _build_resample_page(self):
        page, card = self._new_page()
        card.addWidget(self._field(tr("Boundary layer")))
        self.vectorLayerCombo = QComboBox()
        self.vectorLayerCombo.setToolTip(tr(
            "Polygon layer outlining the field. Any CRS — a geographic boundary "
            "is auto-reprojected to its UTM zone."))
        card.addWidget(self.vectorLayerCombo)
        card.addWidget(self._hint(tr("Polygon outline of the field (any CRS).")))

        card.addWidget(self._field(tr("Input rasters")))
        self.rasterListWidget = QListWidget()
        set_multiselection(self.rasterListWidget)
        self.rasterListWidget.setMinimumHeight(140)
        self.rasterListWidget.setToolTip(tr(
            "Pick one or more rasters to combine. Hold Ctrl or Shift to multi-select."))
        card.addWidget(self.rasterListWidget)
        card.addWidget(self._hint(tr("Select one or more — Ctrl/Shift for multiple.")))

        card.addWidget(self._field(tr("Resolution (m)")))
        self.resolucaoLineEdit = QLineEdit()
        self.resolucaoLineEdit.setPlaceholderText(tr("e.g. 10"))
        self.resolucaoLineEdit.setToolTip(tr(
            "Output pixel size in meters. Match your highest-resolution raster."))
        card.addWidget(self.resolucaoLineEdit)
        card.addWidget(self._hint(tr("Output pixel size in meters; use your finest raster as reference.")))

        self.executarButton = self._primary(QPushButton(tr("Run resampling and extract values")))
        card.addWidget(self.executarButton)
        return page

    def _build_pca_page(self):
        page, card = self._new_page()
        self.pcaButton = self._primary(QPushButton(tr("Run PCA")))
        card.addWidget(self.pcaButton)

        self.pcaTable = QTableWidget()
        self.pcaTable.setColumnCount(4)
        self.pcaTable.setHorizontalHeaderLabels([
            tr("Component"), tr("Eigenvalue (λ)"),
            tr("Variance (%)"), tr("Cumulative (%)")])
        self.pcaTable.setMinimumHeight(160)
        card.addWidget(self.pcaTable)

        self.exportPathButton = self._secondary(QPushButton(
            tr("Choose folder to save")))
        card.addWidget(self.exportPathButton)

        self.exportPath = QLabel(tr("No folder selected"))
        self.exportPath.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        card.addWidget(self.exportPath)

        self.exportButton = self._secondary(QPushButton(
            tr("Export full report (CSV)")))
        card.addWidget(self.exportButton)

        self.pcaExportGroup = QGroupBox(tr("Export PCs as raster"))
        gl = QHBoxLayout(self.pcaExportGroup)
        self.pcExportLabel = self._field(tr("Choose PC:"))
        gl.addWidget(self.pcExportLabel)
        self.pcExportCombo = QComboBox()
        self.pcExportCombo.setEnabled(False)
        self.pcExportCombo.setToolTip(tr("Principal component to write as a single-band raster."))
        gl.addWidget(self.pcExportCombo)
        self.btnExportPCRaster = self._secondary(QPushButton(
            tr("Export selected PC (GeoTIFF)")))
        gl.addWidget(self.btnExportPCRaster)
        self.btnExportAllPCRasters = self._secondary(QPushButton(
            tr("Export all PCs (multi-band)")))
        gl.addWidget(self.btnExportAllPCRasters)
        card.addWidget(self.pcaExportGroup)
        return page

    def _build_zones_page(self):
        page, card = self._new_page()
        self.grpFonte = QGroupBox(tr("Data source for clustering"))
        self.radPCA = QRadioButton(tr("PCA (selected components)"))
        self.radOrig = QRadioButton(tr("Original variables (z-score)"))
        self.radPCA.setChecked(True)
        gLay = QVBoxLayout(self.grpFonte)
        gLay.addWidget(self.radPCA)
        gLay.addWidget(self.radOrig)
        card.addWidget(self.grpFonte)

        pcRow = QHBoxLayout()
        self.pcSelectorLabel = self._field(tr("Number of PCs to use:"))
        pcRow.addWidget(self.pcSelectorLabel)
        self.pcSelector = QComboBox()
        self.pcSelector.setToolTip(tr("How many principal components feed the clustering."))
        pcRow.addWidget(self.pcSelector)
        pcRow.addStretch()
        card.addLayout(pcRow)

        self.radPCA.toggled.connect(self._toggle_pc_selector)
        self._toggle_pc_selector(self.radPCA.isChecked())

        rangeRow = QHBoxLayout()
        self.clusterMinLabel = self._field(tr("Min clusters:"))
        rangeRow.addWidget(self.clusterMinLabel)
        self.clusterMinSpin = QSpinBox()
        self.clusterMinSpin.setMinimum(2)
        self.clusterMinSpin.setMaximum(20)
        self.clusterMinSpin.setValue(2)
        self.clusterMinSpin.setToolTip(tr("Smallest number of clusters (k) to evaluate."))
        rangeRow.addWidget(self.clusterMinSpin)
        self.clusterMaxLabel = self._field(tr("Max clusters:"))
        rangeRow.addWidget(self.clusterMaxLabel)
        self.clusterMaxSpin = QSpinBox()
        self.clusterMaxSpin.setMinimum(2)
        self.clusterMaxSpin.setMaximum(20)
        self.clusterMaxSpin.setValue(10)
        self.clusterMaxSpin.setToolTip(tr("Largest number of clusters (k) to evaluate."))
        rangeRow.addWidget(self.clusterMaxSpin)
        rangeRow.addStretch()
        card.addLayout(rangeRow)
        card.addWidget(self._hint(tr("Evaluates every k in this range with Elbow + Silhouette.")))

        self.executarZonasButton = self._primary(QPushButton(tr("Run zones analysis (KMeans + Elbow + Silhouette)")))
        card.addWidget(self.executarZonasButton)

        self.indicesTable = QTableWidget()
        self.indicesTable.setColumnCount(3)
        self.indicesTable.setHorizontalHeaderLabels([
            tr("Clusters"), tr("Inertia"), tr("Silhouette")])
        self.indicesTable.setMinimumHeight(120)
        card.addWidget(self.indicesTable)

        self.elbowCanvas = FigureCanvas(Figure(figsize=(4, 2)))
        self.elbowCanvas.setMinimumHeight(200)
        card.addWidget(self.elbowCanvas)
        self.elbowAxes = self.elbowCanvas.figure.add_subplot(111)

        self.exportElbowButton = self._secondary(QPushButton(
            tr("Export plot (Elbow + Silhouette) [PNG]")))
        card.addWidget(self.exportElbowButton)
        self.exportZonasButton = self._secondary(QPushButton(
            tr("Export results (Elbow + Silhouette) [CSV]")))
        card.addWidget(self.exportZonasButton)

        finalRow = QHBoxLayout()
        self.finalClusterLabel = self._field(tr("Number of zones to generate (KMeans):"))
        finalRow.addWidget(self.finalClusterLabel)
        self.finalClusterSpin = QSpinBox()
        self.finalClusterSpin.setMinimum(2)
        self.finalClusterSpin.setMaximum(20)
        self.finalClusterSpin.setValue(3)
        self.finalClusterSpin.setToolTip(tr("Final k — the number of management zones in the output raster."))
        finalRow.addWidget(self.finalClusterSpin)
        finalRow.addStretch()
        card.addLayout(finalRow)
        card.addWidget(self._hint(tr("Pick k from the Elbow/Silhouette results above.")))

        self.gerarZonasButton = self._primary(QPushButton(
            tr("Generate management zones (as raster)")))
        card.addWidget(self.gerarZonasButton)
        return page

    def _build_filter_page(self):
        page, card = self._new_page()
        card.addWidget(self._field(tr("Zones raster to smooth")))
        self.rasterFiltroCombo = QComboBox()
        self.rasterFiltroCombo.setToolTip(tr("The management-zones raster to smooth (e.g. one just generated)."))
        card.addWidget(self.rasterFiltroCombo)

        card.addWidget(self._field(tr("Window size (e.g., 3, 5, 7):")))
        self.windowSizeSpin = QSpinBox()
        self.windowSizeSpin.setMinimum(3)
        self.windowSizeSpin.setMaximum(99)
        self.windowSizeSpin.setSingleStep(2)
        self.windowSizeSpin.setValue(5)
        self.windowSizeSpin.setToolTip(tr("Filter radius in pixels; larger = smoother, fewer speckles."))
        card.addWidget(self.windowSizeSpin)

        card.addWidget(self._hint(tr("Window size: 3 = 7x7 pixels, 5 = 11x11 pixels, etc.")))

        self.executarFiltroButton = self._primary(QPushButton(
            tr("Run Mode Filter")))
        card.addWidget(self.executarFiltroButton)
        return page

    def _build_analysis_page(self):
        page, card = self._new_page()
        card.addWidget(self._field(tr("Zones raster (already in QGIS):")))
        self.zonasRasterCombo = QComboBox()
        self.zonasRasterCombo.setToolTip(tr("Zones raster to summarize per zone."))
        card.addWidget(self.zonasRasterCombo)

        self.resultadoVRLabel = QLabel("VR: -")
        self.resultadoVRLabel.setStyleSheet("font-weight: bold; color: #37474F;")
        card.addWidget(self.resultadoVRLabel)

        self.resultadoTabela = QTableWidget()
        self.resultadoTabela.setColumnCount(5)
        self.resultadoTabela.setHorizontalHeaderLabels([
            tr("Zone"), tr("Mean"), tr("Variance"),
            "n", tr("Area (ha)")])
        self.resultadoTabela.setMinimumHeight(140)
        card.addWidget(self.resultadoTabela)

        card.addWidget(self._field(tr("Or load CSV with external data:")))
        self.botaoCarregarCSV = self._secondary(QPushButton(
            tr("Load points CSV")))
        self.botaoCarregarCSV.setToolTip(tr("CSV with coordinate columns and the attribute to analyze."))
        card.addWidget(self.botaoCarregarCSV)
        card.addWidget(self._hint(tr("Map the CSV columns below after loading.")))

        card.addWidget(self._field(tr("X column (longitude):")))
        self.colunaXCombo = QComboBox()
        self.colunaXCombo.setToolTip(tr("CSV column holding the X / longitude coordinate."))
        card.addWidget(self.colunaXCombo)
        card.addWidget(self._field(tr("Y column (latitude):")))
        self.colunaYCombo = QComboBox()
        self.colunaYCombo.setToolTip(tr("CSV column holding the Y / latitude coordinate."))
        card.addWidget(self.colunaYCombo)
        card.addWidget(self._field(tr("Attribute column:")))
        self.colunaAtributoCombo = QComboBox()
        self.colunaAtributoCombo.setToolTip(tr("CSV column with the numeric value to summarize per zone."))
        card.addWidget(self.colunaAtributoCombo)

        self.executarAnaliseButton = self._primary(QPushButton(
            tr("Run Variance Reduction")))
        card.addWidget(self.executarAnaliseButton)
        self.exportarBoxplotsButton = self._secondary(QPushButton(
            tr("Export boxplots (PNG)")))
        card.addWidget(self.exportarBoxplotsButton)
        return page

    # --------------------------------------------------- navigation
    def _go_to_page(self, key):
        if key in self.pages:
            self.stack.setCurrentWidget(self.pages[key])

    def _sync_page_state(self, index):
        widget = self.stack.widget(index)
        key = None
        for k, w in self.pages.items():
            if w is widget:
                key = k
                break
        if key is None:
            return
        self._page_title.setText(_PAGE_TITLES.get(key, ""))
        self.sidebar.set_active_page(key)
        idx = ORDER.index(key)
        self._navBack.setEnabled(idx > 0)
        self._navNext.setEnabled(idx < len(ORDER) - 1)
        self._navStep.setText(f"{idx + 1} / {len(ORDER)}")
        if key in ("filter", "analysis"):
            self.atualizar_lista_rasters()

    # --------------------------------------------------- UI helpers
    def atualizar_lista_rasters(self):
        self.rasterFiltroCombo.clear()
        self.zonasRasterCombo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer):
                self.rasterFiltroCombo.addItem(layer.name())
                self.zonasRasterCombo.addItem(layer.name())

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
