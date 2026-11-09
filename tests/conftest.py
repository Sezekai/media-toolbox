import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def places(tmp_path, monkeypatch):
    """Every test gets its own app root and data folder."""
    monkeypatch.setenv("MEDIATOOLBOX_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("MEDIATOOLBOX_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("APPDATA", raising=False)
    yield tmp_path
