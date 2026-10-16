"""공통 테스트 fixture."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mps.common.config import DATA_ROOT_ENV, DEFAULT_CONFIG_DIR


@pytest.fixture(autouse=True)
def _isolate_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """모든 테스트에서 데이터 루트를 임시 폴더로 돌려 실제 ~/datas/mpp 를 건드리지 않게 한다."""
    root = tmp_path / "data_root"
    monkeypatch.setenv(DATA_ROOT_ENV, str(root))
    return root


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """저장소 config/ 의 복사본. 테스트에서 자유롭게 수정해도 원본은 그대로다."""
    dst = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, dst)
    return dst
