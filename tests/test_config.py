"""config 로더 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mps.common import config as cfg
from mps.common.config import ConfigError


def _edit(config_dir: Path, name: str, **changes: object) -> None:
    """config_dir/name 의 최상위 항목을 바꿔 다시 쓴다."""
    path = config_dir / name
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.update(changes)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


# ----- 저장소 기본 설정 -----

def test_repo_default_trading_mode_is_paper() -> None:
    """저장소 기본값은 반드시 모의투자여야 한다."""
    assert cfg.load_trading_mode() == cfg.PAPER
    assert cfg.is_live() is False


def test_repo_default_files_load() -> None:
    assert [s.code for s in cfg.load_symbols()] == ["005930"]
    costs = cfg.load_costs()
    assert costs.sell_tax_rate == pytest.approx(0.002)
    limits = cfg.load_risk_limits()
    assert limits.max_trades_per_day >= 1


# ----- 경로 -----

def test_data_root_from_env(_isolate_data_root: Path) -> None:
    paths = cfg.load_paths()
    assert paths.data_root == _isolate_data_root.resolve()
    assert paths["raw_ticks"] == _isolate_data_root.resolve() / "raw" / "ticks"
    assert not paths.data_root.exists()  # 로더는 폴더를 만들지 않는다


def test_data_root_falls_back_to_yaml(monkeypatch: pytest.MonkeyPatch, config_dir: Path, tmp_path: Path) -> None:
    monkeypatch.delenv(cfg.DATA_ROOT_ENV)
    _edit(config_dir, "paths.yaml", data_root=str(tmp_path / "from_yaml"))
    assert cfg.load_paths(config_dir).data_root == (tmp_path / "from_yaml").resolve()


def test_missing_config_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        cfg.load_paths(tmp_path / "nowhere")


# ----- 종목 -----

def test_symbol_code_must_be_quoted_six_digits(config_dir: Path) -> None:
    (config_dir / "symbols.yaml").write_text("symbols:\n  - code: 5930\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        cfg.load_symbols(config_dir)


def test_duplicate_symbol_rejected(config_dir: Path) -> None:
    item = {"code": "005930", "name": "삼성전자", "market": "KOSPI", "enabled": True}
    _edit(config_dir, "symbols.yaml", symbols=[item, item])
    with pytest.raises(ConfigError):
        cfg.load_symbols(config_dir)


def test_disabled_symbols_filtered(config_dir: Path) -> None:
    items = [
        {"code": "005930", "name": "삼성전자", "market": "KOSPI", "enabled": True},
        {"code": "000660", "name": "SK하이닉스", "market": "KOSPI", "enabled": False},
    ]
    _edit(config_dir, "symbols.yaml", symbols=items)
    assert [s.code for s in cfg.load_symbols(config_dir)] == ["005930"]
    assert len(cfg.load_symbols(config_dir, enabled_only=False)) == 2


def test_too_many_enabled_symbols_rejected(config_dir: Path) -> None:
    items = [{"code": f"{i:06d}", "enabled": True} for i in range(1, 4)]
    _edit(config_dir, "symbols.yaml", max_symbols=2, symbols=items)
    with pytest.raises(ConfigError):
        cfg.load_symbols(config_dir)


@pytest.mark.parametrize("value", [0, 10])
def test_max_symbols_must_be_below_ten(config_dir: Path, value: int) -> None:
    _edit(config_dir, "symbols.yaml", max_symbols=value)
    with pytest.raises(ConfigError):
        cfg.load_symbols(config_dir)


# ----- 비용 -----

def test_tick_table_last_band_unbounded(config_dir: Path) -> None:
    _edit(config_dir, "costs.yaml", tick_size_table=[{"below": 2000, "tick": 1}])
    with pytest.raises(ConfigError):
        cfg.load_costs(config_dir)


def test_tick_table_must_be_ascending(config_dir: Path) -> None:
    table = [{"below": 5000, "tick": 5}, {"below": 2000, "tick": 1}, {"below": None, "tick": 10}]
    _edit(config_dir, "costs.yaml", tick_size_table=table)
    with pytest.raises(ConfigError):
        cfg.load_costs(config_dir)


def test_negative_rate_rejected(config_dir: Path) -> None:
    _edit(config_dir, "costs.yaml", commission_rate=-0.001)
    with pytest.raises(ConfigError):
        cfg.load_costs(config_dir)


def test_missing_cost_key_rejected(config_dir: Path) -> None:
    (config_dir / "costs.yaml").write_text("sell_tax_rate: 0.002\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        cfg.load_costs(config_dir)


# ----- 리스크 한도 -----

@pytest.mark.parametrize(
    "changes",
    [
        {"daily_loss_limit_rate": 0},
        {"max_trades_per_day": 0},
        {"max_consecutive_losses": 0},
        {"max_weight_per_symbol": 1.5},
        {"force_close_time": "25:00"},
        {"force_close_time": "1515"},
        {"kill_switch_file": ""},
    ],
)
def test_invalid_risk_limits_rejected(config_dir: Path, changes: dict[str, object]) -> None:
    _edit(config_dir, "risk_limits.yaml", **changes)
    with pytest.raises(ConfigError):
        cfg.load_risk_limits(config_dir)


# ----- 실전/모의 전환 -----

def test_missing_mode_defaults_to_paper(config_dir: Path) -> None:
    (config_dir / "trading_mode.yaml").write_text("# empty\n", encoding="utf-8")
    assert cfg.load_trading_mode(config_dir) == cfg.PAPER


@pytest.mark.parametrize("value", ["real", "LIVE!", "", 1, None])
def test_unknown_mode_is_error_not_live(config_dir: Path, value: object) -> None:
    _edit(config_dir, "trading_mode.yaml", mode=value)
    with pytest.raises(ConfigError):
        cfg.load_trading_mode(config_dir)


def test_live_only_when_explicitly_set(config_dir: Path) -> None:
    _edit(config_dir, "trading_mode.yaml", mode="live")
    assert cfg.is_live(config_dir) is True
