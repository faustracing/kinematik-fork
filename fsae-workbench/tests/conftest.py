from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Lets the suite run from a plain checkout, before the package is installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(20260101)
