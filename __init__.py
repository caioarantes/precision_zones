import os
import sys

_plugin_dir = os.path.dirname(__file__)
_extlibs_path = os.path.join(_plugin_dir, "extlibs")

if os.path.isdir(_extlibs_path) and _extlibs_path not in sys.path:
    sys.path.insert(0, _extlibs_path)


def classFactory(iface):
    if not os.path.isdir(_extlibs_path) or not os.listdir(_extlibs_path):
        from . import extlibs_manager
        extlibs_manager.start_download()

    from .precision_zones import PrecisionZonesPlugin
    return PrecisionZonesPlugin(iface)
