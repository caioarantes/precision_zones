# Precision Zones (QGIS Plugin)

**Precision Zones** streamlines end-to-end **Management Zone** delineation in QGIS: raster preprocessing, value extraction, PCA, Elbow/K-Means analysis, zone raster generation, majority (mode) filtering with SAGA, and per-zone statistics including **Variance Reduction (VR%)** and **boxplots**.

> UI language: **EN by default**. Switches to **PT-BR** automatically if your QGIS/system locale is Portuguese (or set `PZ_FORCE_LANG=pt`, or `QSettings PrecisionZones/lang=pt*`).

---

## Requirements

- **QGIS 3.34 LTR or newer** (developed/tested on QGIS **3.44 LTR**, bundled **Python 3.12**, Windows).
- **SAGA provider** enabled in QGIS — only for the majority (mode) filter. Install the *Processing Saga NextGen Provider* plugin via **Plugins ▶ Manage and Install…**.
- GDAL / Processing — included with QGIS.
- Python deps `pandas`, `scikit-learn`, `scipy` — **downloaded automatically** on first launch (see below). `numpy` and `matplotlib` ship with QGIS.

### Dependencies (auto-managed)

Third-party Python packages not bundled with QGIS are vendored in **`extlibs.zip`** and downloaded from GitHub into a local `extlibs/` folder on first run, then added to `sys.path` — no manual `pip` needed.

- `extlibs.zip` contains: `pandas`, `scikit-learn`, `scipy` (+ their deps), built for **cp312 / win_amd64** to match QGIS LTR's Python.
- On other platforms / Python versions, install manually instead (OSGeo4W Shell):
  ```
  pip install pandas scikit-learn scipy
  ```

---

## Features

- **Raster preprocessing**
  - Reproject + **resample** to a user-defined resolution, clip to the boundary (GDAL `gdal:warpreproject`, `gdal:cliprasterbymasklayer`).
  - Generate **centroid points** from the reference raster (`native:pixelstopoints`).
  - **Extract values** from all rasters to those points (`qgis:rastersampling`).
  - Automatic data cleaning (NoData / Inf / sentinels) + drop zero-variance columns.

- **PCA (scikit-learn)**
  - **z-score** standardization, per-component and cumulative explained variance table.
  - Export loadings/variances as **CSV**; export PCs as single-band or multi-band **GeoTIFF**.

- **Elbow & K-Means (scikit-learn)**
  - Elbow + silhouette for **k = kmin…kmax** using selected **PCs** or **original variables** (z-score).
  - Export **PNG** (plot) and **CSV** (inertia/silhouette table).

- **Zone raster generation**
  - K-Means clustering (PCs or originals), rasterized to an aligned **GeoTIFF** (UInt16) on the reference grid.

- **Majority filter (SAGA)**
  - `sagang:majorityminorityfilter` / `saga:majorityfilter` (auto-detected).
  - **Aligns** output to the original grid (GDAL Warp) without inflating areas; **preserves zone IDs** via overlap-based remapping.

- **Per-zone analysis**
  - Read external CSV (X, Y, attribute) and map points to zones via geotransform.
  - Per-zone stats: n, area ha/%, mean, median, **variance**, min/max, Q1/Q3, IQR, **CV%**, **95% CI**, **skewness**.
  - **Area-weighted total VR%**; export per-zone **CSV** and **boxplots (PNG)** (“All vs. Zones”).

---

## Installation

- **From ZIP (manual)**
  1. Zip the `precision_zones/` folder.
  2. QGIS → **Plugins → Install from ZIP** → select the `.zip`.
  3. On first launch the plugin downloads `extlibs.zip` (pandas/scikit-learn/scipy).

- **From the Official QGIS Plugin Repository**
  Once published, search for **“Precision Zones”** in the QGIS plugin manager.

---

## UI overview

The dialog uses a **navigation sidebar** (hover to expand) with one page per step:

**Resampling · PCA · Zones · Mode Filter · Analysis**

1. **Resampling** — pick the boundary vector (UTM/metric CRS), select rasters, set resolution (m/pixel) → centroids + extracted values, cleaned in memory.
2. **PCA** — Run PCA; inspect explained/cumulative variance; export CSVs or PC rasters.
3. **Zones** — choose PCA (n PCs) or original variables; set k-range → Elbow + Silhouette; export PNG/CSV; set final k → **Generate Zones** (GeoTIFF added to project).
4. **Mode Filter** — pick a zones raster, set window radius → SAGA majority filter, aligned to the grid.
5. **Analysis** — load CSV (X, Y, attribute), pick the zones raster + columns → per-zone table + **total VR%**; export CSV and boxplots.

---

## I/O and Formats

- **Inputs:** rasters (any GDAL-readable), boundary vector, CSV (X, Y, attribute).
- **Outputs:**
  - `zonas_manejo_k{K}_{PCA|Orig}.tif` (UInt16, aligned to the reference grid)
  - `pca_componentes.csv`, `pca_variancia.csv`
  - Elbow plot `.png` and table `.csv`
  - per-zone statistics `.csv` (includes total VR%) and boxplots `.png`

---

## Architecture

The plugin is organized in AGLgis-style layers:

```
precision_zones/
  precision_zones.py    # plugin entry: builds session/notifier/controllers, wires signals
  core/                 # i18n, qt_compat, notify, deps, session (shared state), raster_io
  services/             # pure backend: resampling, pca, clustering, zones, filter, variance, export
  view/                 # UI only: main_dialog (header + sidebar + stacked pages), sidebar, styles
  controllers/          # one per page: orchestrate view <-> services
  extlibs_manager.py    # downloads/extracts extlibs.zip on first run
```

---

## Troubleshooting

- **Missing dependency:** dependencies download automatically on first launch; if offline, install `pandas` / `scikit-learn` / `scipy` in the QGIS Python env manually.
- **SAGA not available:** install/enable the **SAGA NextGen** provider in *Plugins ▶ Manage and Install…* / *Processing → Providers*.
- **Invalid CRS:** the boundary must be in a **projected (metric/UTM)** CRS, not geographic degrees.
- **Export errors:** choose an **export folder** first (button on the PCA page).

---

## License
GPL-2.0-or-later

## Authors
Derlei Melo; Isabella Cunha; Lucas Amaral.
