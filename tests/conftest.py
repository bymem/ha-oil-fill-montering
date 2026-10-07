"""Make the pure-logic modules importable without Home Assistant.

The integration package's __init__ imports Home Assistant. Registering an
empty `oil_tank` package that points at the integration folder lets tests
import the pure modules (and their relative imports) without running it.
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).parent.parent
INTEGRATION_DIR = ROOT / "custom_components" / "oil_tank"

_package = types.ModuleType("oil_tank")
_package.__path__ = [str(INTEGRATION_DIR)]
sys.modules["oil_tank"] = _package

FIXTURES = Path(__file__).parent / "fixtures"
