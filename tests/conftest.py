"""Make the pure-logic modules importable without Home Assistant.

The integration package's __init__ imports Home Assistant, so the pure
modules (feed, prices, csv_io) are imported as top-level modules instead.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "oil_tank"))

FIXTURES = Path(__file__).parent / "fixtures"
