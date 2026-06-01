# -*- coding: utf-8 -*-
"""Build extlibs.zip from a pip --target build dir.

Usage: python build_extlibs_zip.py <build_dir> <out_zip>
Writes every file under <build_dir> into <out_zip> beneath an "extlibs/" prefix,
matching what extlibs_manager.ExtlibsDownloader expects.
"""
import os
import sys
import zipfile


def main():
    src = sys.argv[1]
    out = sys.argv[2]
    zf = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9)
    n = 0
    for root, _, files in os.walk(src):
        for f in files:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, src).replace(os.sep, "/")
            zf.write(fp, "extlibs/" + rel)
            n += 1
    zf.close()
    print("files", n, "zip MB", round(os.path.getsize(out) / 1e6, 1))


if __name__ == "__main__":
    main()
