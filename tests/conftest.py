import pytest
from pathlib import Path

@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path
