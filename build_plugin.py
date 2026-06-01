#!/usr/bin/env python3
"""Build the Precision Zones distribution zip (QGIS "Install from ZIP").

Compiles translations, then packages the runtime code under a top-level
``precision_zones/`` folder into ``dist/precision_zones.zip``.

The heavy Python dependencies (pandas/scikit-learn/scipy) are NOT bundled — they
are fetched at first run from the GitHub-hosted ``extlibs.zip`` by
``extlibs_manager.py`` — so this zip stays small.

Usage (OSGeo4W Shell):
    python-qgis-ltr build_plugin.py
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

PLUGIN_NAME = "precision_zones"
ROOT = Path(__file__).parent.resolve()
DIST_DIR = ROOT / "dist"
ZIP_PATH = DIST_DIR / f"{PLUGIN_NAME}.zip"

# Runtime files (dev/build scripts and the bundled extlibs.zip are excluded).
INCLUDE_FILES = [
    "__init__.py",
    "precision_zones.py",
    "extlibs_manager.py",
    "metadata.txt",
    "requirements.txt",
    "icon.png",
    "resources_rc.py",
    "README.md",
    "LICENSE",
]

INCLUDE_DIRS = ["core", "services", "controllers", "view"]

SKIP_PARTS = {"__pycache__", ".git", ".github", "dist", ".mypy_cache", ".pytest_cache"}


def step(msg: str) -> None:
    print(f"\n[{msg}]")


def compile_translations() -> None:
    step("Compile translations")
    script = ROOT / "compile_translations.py"
    if script.exists():
        subprocess.run([sys.executable, str(script)], check=True, cwd=ROOT)
    else:
        print("  compile_translations.py not found — skipping")


def build_zip() -> None:
    step("Build zip")
    DIST_DIR.mkdir(exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for filename in INCLUDE_FILES:
            src = ROOT / filename
            if src.exists():
                zf.write(src, f"{PLUGIN_NAME}/{filename}")
                print(f"  + {filename}")
            else:
                print(f"  ! missing (skipped): {filename}")

        i18n_dir = ROOT / "i18n"
        if i18n_dir.exists():
            qms = sorted(i18n_dir.glob("*.qm"))
            for qm in qms:
                zf.write(qm, f"{PLUGIN_NAME}/i18n/{qm.name}")
            print(f"  + i18n/ ({len(qms)} .qm files)")

        for dirname in INCLUDE_DIRS:
            src = ROOT / dirname
            if not src.exists():
                print(f"  ! missing dir (skipped): {dirname}/")
                continue
            files = [
                p for p in src.rglob("*")
                if p.is_file() and not any(part in SKIP_PARTS for part in p.relative_to(ROOT).parts)
            ]
            for p in sorted(files):
                zf.write(p, f"{PLUGIN_NAME}/{p.relative_to(ROOT).as_posix()}")
            print(f"  + {dirname}/ ({len(files)} files)")

    size_kb = ZIP_PATH.stat().st_size / 1024
    print(f"\nDone: dist/{PLUGIN_NAME}.zip ({size_kb:.0f} KB)")


def main() -> None:
    print(f"Building {PLUGIN_NAME} ...")
    compile_translations()
    build_zip()


if __name__ == "__main__":
    main()
