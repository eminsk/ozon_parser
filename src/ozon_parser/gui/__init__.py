"""
Desktop GUI entry point for Ozon SDK Pro (`ozon-gui`).
"""

from __future__ import annotations

import sys
from typing import List, Optional


def main_gui(argv: Optional[List[str]] = None) -> int:
    """Launch the CustomTkinter Ozon SDK Pro Desktop application."""
    from ozon_parser.gui.app import OzonGUIApp

    try:
        app = OzonGUIApp()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main_gui())
