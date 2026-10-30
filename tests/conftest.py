"""Make the pure-logic modules importable without Home Assistant.

The integration package's __init__ imports Home Assistant. Registering an
empty `oil_tank` package that points at the integration folder lets tests
import the pure modules (and their relative imports) without running it.
"""

import json
import sys
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
INTEGRATION_DIR = ROOT / "custom_components" / "oil_tank"

_package = types.ModuleType("oil_tank")
_package.__path__ = [str(INTEGRATION_DIR)]
sys.modules["oil_tank"] = _package

FIXTURES = Path(__file__).parent / "fixtures"


def load_price_fixture() -> list:
    """Two years of daily prices (2024-10-07 to 2026-10-07), oldest first.

    Saved from the previous supplier's feed, which is gone; kept as test data
    for the stats and decision logic. Format:
    {"prices":{"price":[{"@_date":"07.10.2024","value":16437.25}, ...]}}
    """
    rows = json.loads((FIXTURES / "feed_2026-10-07.json").read_text())["prices"]["price"]
    return sorted(
        (datetime.strptime(row["@_date"], "%d.%m.%Y").date(), float(row["value"])) for row in rows
    )
