# Precision Zones (QGIS Plugin)

**Precision Zones** streamlines end-to-end **Management Zone** delineation in QGIS: raster preprocessing, value extraction, PCA, Elbow/K-Means analysis, zone raster generation, majority (mode) filtering, and per-zone statistics including **Variance Reduction (VR%)** and **boxplots**.

> UI language: **English by default**, following the QGIS UI locale (`Settings ▶ Options ▶ General`). Bundled translations: English (source), Portuguese (pt_BR), Spanish, French, Italian — plus partial Hindi and Chinese (untranslated strings fall back to English). Translations use Qt `.ts`/`.qm` under `i18n/`; rebuild with `python compile_translations.py`.

---

## Requirements

- **QGIS 3.28 or newer**, including Qt6-based QGIS 4.x (verified on QGIS **3.44 LTR** and **4.0**). Prebuilt dependency bundles cover Windows, Linux and macOS across Python 3.9–3.12; other setups use the automatic pip fallback.
- GDAL / Processing — included with QGIS.
- Python deps `pandas`, `scikit-learn`, `scipy` — **downloaded automatically** on first launch (see below). `numpy` and `matplotlib` ship with QGIS.

### Dependencies (auto-managed, multi-version)

Third-party packages not bundled with QGIS (`pandas`, `scikit-learn`, `scipy`) are provisioned into a local `extlibs/` folder on first run and added to `sys.path` — no manual `pip` needed. The provisioning matches the **running QGIS Python**, so different QGIS versions work automatically. On first run, `extlibs_manager` tries, in order:

1. **Prebuilt zip** tagged for this interpreter: `extlibs-<cpXY>-<platform>.zip` (e.g. `extlibs-cp312-win_amd64.zip`) — fast.
2. **Runtime pip** — runs the QGIS Python's `pip` to install `requirements.txt` into `extlibs/` (works on any Python/OS with internet); `numpy`/`matplotlib` are dropped afterward since QGIS provides them.
3. **Manual** — if both fail, install `pandas scikit-learn scipy` in the QGIS Python yourself.

The active build is recorded in `extlibs/.ready` with its tag; a QGIS Python upgrade re-provisions automatically. Prebuilt zips are published for Windows (cp39–cp312), Linux (cp310–cp312) and macOS (cp312); any combination without a prebuilt zip uses the pip fallback. New bundles are produced by the **Build extlibs** GitHub Actions workflow.

You can also check/install dependencies from the plugin's **Intro page**: status chips for pandas / scikit-learn / scipy, an **Install dependencies** button, and a **Manual install…** dialog with the exact `pip` command.

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

- **Majority filter (built-in)**
  - Circular-kernel modal filter computed in-process with numpy/scipy — no SAGA provider needed.
  - Runs directly on the source grid, so zone IDs and alignment are preserved by construction.

- **Per-zone analysis**
  - Read external CSV (X, Y, attribute) and map points to zones via geotransform.
  - Per-zone stats: n, area ha/%, mean, median, **variance**, min/max, Q1/Q3, IQR, **CV%**, **95% CI**, **skewness**.
  - **Area-weighted total VR%**; export per-zone **CSV** and **boxplots (PNG)** (“All vs. Zones”).

---

## Installation

- **From ZIP**
  1. Build the package: `python-qgis-ltr build_plugin.py` → `dist/precision_zones.zip` (or zip the `precision_zones/` folder manually).
  2. QGIS → **Plugins → Install from ZIP** → select the `.zip`.
  3. On first launch the plugin provisions its dependencies (matching prebuilt bundle, else pip).

- **From the Official QGIS Plugin Repository**
  Once published, search for **“Precision Zones”** in the QGIS plugin manager.

---

## UI overview

The dialog is a resizable, non-modal window (minimize/maximize/close) with a **navigation sidebar** (hover to expand) and a fixed **Back / Next** bar to step through the workflow:

**Intro · Resampling · PCA · Zones · Mode Filter · Analysis**

0. **Intro** — overview, features, the required citation, and a live dependency panel (install / recheck / manual install).
1. **Resampling** — pick the boundary vector (any CRS; a geographic/degrees boundary is **auto-reprojected to its appropriate UTM zone**), select rasters, set resolution (m/pixel) → centroids + extracted values, cleaned in memory.
2. **PCA** — Run PCA; inspect explained/cumulative variance; export CSVs or PC rasters.
3. **Zones** — choose PCA (n PCs) or original variables; set k-range → Elbow + Silhouette; export PNG/CSV; set final k → **Generate Zones** (GeoTIFF added to project).
4. **Mode Filter** — pick a zones raster, set window radius → built-in majority filter on the source grid.
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
  extlibs_manager.py    # provisions the matching extlibs-<tag>.zip (or pip) on first run
  intro.html / intro_pt_br.html   # Intro page content
  i18n/                 # Qt .ts/.qm translations
  .github/workflows/    # CI: build extlibs bundles
```

---

## Development

Helper scripts (run with QGIS' Python, e.g. `python-qgis-ltr`):

- **`build_plugin.py`** — compiles translations and packages the runtime code into `dist/precision_zones.zip` (deps excluded; fetched at runtime).
- **`compile_translations.py`** — compiles `i18n/*.ts` → `*.qm` (pure Python, no `lrelease`). Run after editing any `.ts`.
- **`build_extlibs_zip.py`** — run with **no args** under a target QGIS Python to build `extlibs-<tag>.zip` (e.g. `extlibs-cp312-win_amd64.zip`) for that interpreter; pip-installs deps, strips numpy/matplotlib, zips. To support another QGIS version, run it under that QGIS's Python and commit + push the resulting `extlibs-<tag>.zip`. (Two-arg mode zips an existing `pip --target` dir.)
- **Build extlibs (GitHub Actions)** — `Actions ▶ Build extlibs ▶ Run workflow` builds the bundles across a Windows/Linux/macOS × Python matrix; enable the **commit** input to push the resulting `extlibs-<tag>.zip` files to `main` automatically (no need to have every QGIS installed locally).

Adding a language: copy an existing `i18n/precision_zones_<lang>.ts`, translate the `<translation>` entries (keep `{}` placeholders), run `compile_translations.py`, and map the locale in `core/i18n.install_translator` if its two-letter code differs (e.g. `pt`→`pt_BR`).

---

## Troubleshooting

- **Missing dependency:** dependencies download automatically on first launch; if offline, install `pandas` / `scikit-learn` / `scipy` in the QGIS Python env manually.
- **CRS:** a geographic (degrees) boundary is auto-reprojected to its UTM zone; a projected boundary is used as-is. Resolution is always in meters.
- **Export errors:** choose an **export folder** first (button on the PCA page).

---

## Citation

Any published work using this plugin **must cite**:

> Melo, D. D., Cunha, I. A., & Amaral, L. R. (2025). *Precision Zones: An Open-Source QGIS Plugin for Management-Zone Segmentation in Precision Agriculture.* AgriEngineering, 7(12), 420. https://www.mdpi.com/2624-7402/7/12/420 — DOI: [10.3390/agriengineering7120420](https://doi.org/10.3390/agriengineering7120420)

---

## License
GPL-2.0-or-later

## Authors
Derlei Melo; Isabella Cunha; Lucas Amaral.
