# -*- coding: utf-8 -*-
"""Majority (modal) filter via SAGA, aligned back to the source grid and
blended to preserve original zone ids. Pure backend (no QMessageBox).

Note: the output GeoTIFF lives under a temp dir and is consumed directly as the
new layer's source, so that dir is intentionally not deleted here."""
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from typing import Optional

import numpy as np
from osgeo import gdal

from qgis.core import (
    QgsProject,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsApplication,
)
from qgis import processing

from ..core.i18n import tr


@dataclass
class FilterResult:
    out_path: str
    nodata: Optional[float]
    raio: int


def saga_majority_id():
    reg = QgsApplication.processingRegistry()
    if reg.algorithmById('sagang:majorityminorityfilter'):
        return 'sagang:majorityminorityfilter'
    if reg.algorithmById('saga:majorityfilter'):
        return 'saga:majorityfilter'
    if reg.algorithmById('sagang:majorityfilter'):
        return 'sagang:majorityfilter'
    return None


def apply_majority_filter(src_path: str, raster_crs_authid: str,
                          raio: int, threshold: float = 0.0) -> FilterResult:
    """Run SAGA majority filter on src_path, align to its grid, blend to keep
    original ids, write a UInt16 GeoTIFF. Raises Exception(translated)."""
    tipo = 0
    kernel_tipo = 1

    base = os.path.join(tempfile.gettempdir(), "pzmod_" + uuid.uuid4().hex[:8])
    os.makedirs(base, exist_ok=True)
    p_saga = os.path.join(base, "s")
    p_tif = os.path.join(base, "s.tif")
    p_aln = os.path.join(base, "a.tif")
    p_out = os.path.join(base, "m.tif")

    context = QgsProcessingContext()
    context.setTransformContext(QgsProject.instance().transformContext())
    feedback = QgsProcessingFeedback()

    saga_id = saga_majority_id()
    if saga_id is None:
        raise Exception(tr("SAGA não disponível. Ative o provedor SAGA em Processamento.",
                           "SAGA not available. Enable the SAGA provider in Processing."))

    dsA = gdal.Open(src_path)
    if dsA is None:
        raise Exception(tr("Falha ao abrir o raster de entrada.", "Failed to open input raster."))

    gt = dsA.GetGeoTransform()
    width_px = int(dsA.RasterXSize)
    height_px = int(dsA.RasterYSize)

    x_min, y_max = gt[0], gt[3]
    x_max = x_min + gt[1] * width_px
    y_min = y_max + gt[5] * height_px
    extent_str = f"{min(x_min, x_max)},{max(x_min, x_max)},{min(y_min, y_max)},{max(y_min, y_max)}"

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

    if (not created.lower().endswith(".tif")) or (not _valid(created)):
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

    ok = False
    try:
        res_warp = processing.run("gdal:warpreproject", {
            "INPUT": saga_path,
            "SOURCE_CRS": None,
            "TARGET_CRS": raster_crs_authid,
            "RESAMPLING": 0,
            "NODATA": nodata if nodata is not None else 0,
            "TARGET_RESOLUTION": None,
            "TARGET_EXTENT": extent_str,
            "TARGET_EXTENT_CRS": raster_crs_authid,
            "MULTITHREADING": True,
            "DATA_TYPE": 2,
            "EXTRA": f"-tap -ts {width_px} {height_px}",
            "OUTPUT": p_aln
        }, context=context, feedback=feedback)
        candidate = res_warp.get("OUTPUT", p_aln)
        if candidate and os.path.exists(candidate):
            if os.path.normpath(candidate) != os.path.normpath(p_aln):
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
                dstSRS=raster_crs_authid,
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
            mask_cmp = (arrA != 0); fundo_val = 0
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
                for vb, va in map_vb_to_va.items():
                    arrB[arrB == vb] = va

    if nodata is not None:
        valid = (arrA != nodata); nd_out = nodata
    elif zero_bg:
        valid = (arrA != 0); nd_out = 0
    else:
        valid = None; nd_out = None

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
    out_band.FlushCache()
    out_ds.FlushCache()
    out_ds = None

    return FilterResult(out_path=p_out, nodata=nodata, raio=raio)
