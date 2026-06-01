# -*- coding: utf-8 -*-
"""Optional dependency helpers.

Third-party libs (pandas, scikit-learn, scipy) are shipped via extlibs.zip and
may be absent until downloaded. Services call these helpers and raise
`DependencyMissing` on absence; controllers catch it and show the standard
bilingual "install instructions" message.
"""
from .i18n import tr


class DependencyMissing(Exception):
    """Raised when an optional Python package is not importable."""

    def __init__(self, package: str):
        self.package = package
        super().__init__(package)

    def user_message(self) -> str:
        return tr(
            f"Este recurso requer o pacote Python '{self.package}'.\n"
            "Abra a aba Reamostragem e clique em 'Baixar dependências' para instalar.",
            f"This feature requires the Python package '{self.package}'.\n"
            "Open the Resampling tab and click 'Download dependencies' to install.",
        )


def import_pandas():
    try:
        import pandas as pd
        return pd
    except Exception:
        raise DependencyMissing("pandas")


def try_pandas():
    """Return the pandas module or None (for soft checks)."""
    try:
        import pandas as pd
        return pd
    except Exception:
        return None
