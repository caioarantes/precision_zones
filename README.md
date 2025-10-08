# Precision Zones (QGIS Plugin)

**Precision Zones** streamlines end-to-end **Management Zone** delineation in QGIS: raster preprocessing, value extraction, PCA, **Elbow/K-Means + Silhouette** analysis, zone raster generation, majority (mode) filtering with SAGA, and per-zone statistics including **Variance Reduction (VR%)** and **boxplots**.

> UI language: **EN by default**. It switches to **PT-BR** automatically if your QGIS/system locale is Portuguese (or if you set `PZ_FORCE_LANG=pt` or `QSettings PrecisionZones/lang=pt*`).

---

## Requirements
- QGIS **3.34** or newer (ships with **Python 3.10**).
- Python packages in the QGIS env: `pandas`, `scikit-learn` (optional: `scipy`).
- Processing **SAGA** provider enabled.


## Features

- **Raster preprocessing**
  - Clip & reproject to the boundary CRS (GDAL `gdal:cliprasterbymasklayer`).
  - **Resample** to a user-defined resolution.
  - Generate **centroid points** from the reference raster (`native:pixelstopoints`).
  - **Extract values** from all rasters to those points (`qgis:rastersampling`).
  - Automatic data cleaning (NoData/Inf/sentinels) + drop zero-variance columns.

- **PCA (scikit-learn)**
  - **z-score** standardization (mean 0, **std 1**).
  - Per-component and cumulative explained variance table.
  - Exportable **CSV** reports (loadings and variances).

- **Elbow, Silhouette & K-Means (scikit-learn)**
  - Compute **Elbow (inertia)** and **Silhouette score** for **k = kmin…kmax** using either selected **PCs** or **original variables** (z-score).
  - Export **PNG/CSV** for the combined **Elbow + Silhouette** plot and indices table.

- **Zone raster generation**
  - K-Means clustering (PCs or originals).
  - Rasterized labels to aligned **GeoTIFF** (UInt16) using the reference raster grid.
  - Clean, localized layer titles and filenames (e.g., `Zones (k=4, PCA, PCs=2)`).

- **Majority filter (SAGA)**
  - Uses `sagang:majorityminorityfilter` / `saga:majorityfilter` (auto-detected).
  - **Aligns** output to the original raster grid (GDAL Warp) **without inflating areas**.
  - **Preserves zone IDs** when possible (overlap-based remapping).

- **Per-zone analysis**
  - Read external CSV (X, Y, attribute) and map points to zones via geotransform.
  - Per-zone stats: n, area ha/%, mean, median, **variance**, min/max, Q1/Q3, IQR, **CV%**, **95% CI**, **skewness**.
  - **Area-weighted total VR%**.
  - Export per-zone **CSV** and **boxplots (PNG)** (“All vs. Zones”).

---

## Requirements

- **QGIS ≥ 3.34** (bundled Python 3.10+).
- Python deps (in the same QGIS env):
  - `pandas` (tables I/O and cleaning)
  - `scikit-learn` (PCA, StandardScaler, KMeans, **Silhouette**)
  - `scipy` (optional; improves 95% CI and skewness; graceful fallback exists)
- **SAGA provider** enabled in QGIS (for the majority filter).
- GDAL/Processing are included with QGIS.

> Windows (OSGeo4W Shell):
> ```
> pip install pandas scikit-learn scipy
> ```

---

## Installation

- **From ZIP (manual)**  
  1) Zip the `precision_zones/` folder (exclude editor backups like `.bak`).  
  2) QGIS → **Plugins → Install from ZIP** → select the `.zip`.

- **From the Official QGIS Plugin Repository**  
  Once published/approved, search for **“Precision Zones”** in the QGIS plugin manager.

---

## Quick Start

1. **Preprocess & extract**
   - Pick the **boundary vector**.
   - Select **one or more rasters** and set the **resolution** (m/pixel).
   - Run to create **centroids** and **extract values** for all rasters.
   - Data are cleaned and kept in memory.

2. **PCA**
   - Click **Run PCA**.
   - Inspect **explained variance** and **cumulative** variance.
   - Optionally **export** CSVs (loadings, variances).

3. **Elbow + Silhouette (choose k)**
   - Choose **PCA** (n PCs) **or Original variables (z-score)**.
   - Set **k min** and **k max** → **Run Zones** (Elbow + Silhouette).
   - Optionally **export** the combined plot (PNG) and indices table (CSV).

4. **Generate zones**
   - Set **final k** and **PCs** (if using PCA) → **Generate Zones**.
   - The **GeoTIFF** with zones is saved and added to the project.

5. **Majority filter (optional)**
   - Pick the zones raster, set **window radius** (r=1≈3×3, r=2≈5×5, …), and **apply**.
   - Output is **aligned** to the original grid, preserving IDs when possible.

6. **Analyses (VR% & boxplots)**
   - Load a **CSV** (X, Y, numeric attribute).
   - Choose the **zones raster** and the CSV columns (X, Y, attribute).
   - See the **per-zone table** and **total VR%**; **export CSV**.
   - Optionally **export boxplots (PNG)** “All vs. Zones”.

---

## I/O and Formats

- **Inputs:** rasters (any GDAL-readable), boundary vector, CSV (X, Y, attribute).  
- **Outputs:**
  - `zonas_manejo_k{K}_{PCA|Orig}.tif` (UInt16, aligned to reference raster)
  - `variancia_pca.csv`, `componentes_pca.csv`
  - `Elbow_Silhouette.png`, `Elbow_Silhouette.csv`
  - `per_zone_stats.csv` (includes total VR%) and `boxplots.png`

---

## Troubleshooting

- **Missing dependency:** install `pandas` / `scikit-learn` / `scipy` in the QGIS Python env.  
- **SAGA not available:** enable the **SAGA** provider in *Processing → Providers*.  
- **CRS mismatch:** use a boundary and rasters in the **same CRS** (the plugin reprojection step helps).  
- **Export errors:** select an **export folder** first (UI button available).

---

## License
GPL-2.0-or-later

## Authors
Derlei Melo; Isabella Cunha; Lucas Amaral

