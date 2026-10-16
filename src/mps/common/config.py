"""config/ 폴더의 YAML 설정을 읽는 로더.

종목코드·비용·리스크 한도·실전/모의 전환·경로는 코드에 상수로 두지 않고
모두 이 모듈을 통해 config/ 에서 읽는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# 저장소 루트의 config/ 폴더 (src/mps/common/config.py 기준 상위 3단계)
DEFAULT_CONFIG_DIR: Path = Path(__file__).resolve().parents[3] / "config"

DATA_ROOT_ENV: str = "MPP_DATA_ROOT"

PAPER: str = "paper"
LIVE: str = "live"
_TRADING_MODES: frozenset[str] = frozenset({PAPER, LIVE})


class ConfigError(ValueError):
    """설정 파일 내용이 규칙에 맞지 않을 때 발생한다."""


@dataclass(frozen=True)
class Paths:
    """데이터 루트와 하위 폴더 경로.

    data_root: 데이터 루트 절대 경로
    subdirs: 하위 폴더 이름 → 절대 경로
    """

    data_root: Path
    subdirs: dict[str, Path]

    def __getitem__(self, key: str) -> Path:
        return self.subdirs[key]


@dataclass(frozen=True)
class Symbol:
    """매매 대상 종목 한 건."""

    code: str
    name: str
    market: str
    enabled: bool


@dataclass(frozen=True)
class TickBand:
    """호가단위 구간. 가격이 below 미만이면 tick 적용 (below=None은 상한 없음). 단위: 원."""

    below: int | None
    tick: int


@dataclass(frozen=True)
class Costs:
    """비용 모델. 비율은 소수(0.002 = 0.20%), 슬리피지는 편도 틱 수."""

    sell_tax_rate: float
    commission_rate: float
    slippage_ticks: int
    price_limit_rate: float
    tick_size_table: tuple[TickBand, ...]


@dataclass(frozen=True)
class RiskLimits:
    """리스크 한도. 비율은 소수, force_close_time 은 KST "HH:MM"."""

    daily_loss_limit_rate: float
    max_trades_per_day: int
    max_consecutive_losses: int
    max_concurrent_positions: int
    max_weight_per_symbol: float
    max_weight_per_sector: float
    force_close_time: str
    kill_switch_file: str


def _read_yaml(name: str, config_dir: Path | None) -> dict[str, Any]:
    """config_dir/name 을 읽어 dict로 반환한다. 파일이 없거나 최상위가 dict가 아니면 ConfigError."""
    path = (config_dir or DEFAULT_CONFIG_DIR) / name
    if not path.is_file():
        raise ConfigError(f"설정 파일이 없습니다: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"설정 파일 최상위는 매핑이어야 합니다: {path}")
    return data


def load_paths(config_dir: Path | None = None) -> Paths:
    """데이터 루트와 하위 폴더 경로를 읽는다.

    입력: config_dir (None이면 저장소 config/)
    출력: Paths. 데이터 루트는 환경변수 MPP_DATA_ROOT → paths.yaml data_root 순으로 정한다.
    폴더를 만들지는 않는다.
    """
    data = _read_yaml("paths.yaml", config_dir)
    root_str = os.environ.get(DATA_ROOT_ENV) or data.get("data_root")
    if not root_str:
        raise ConfigError("data_root 가 정해지지 않았습니다 (MPP_DATA_ROOT 또는 paths.yaml)")
    data_root = Path(root_str).expanduser().resolve()
    subdirs = {key: data_root / rel for key, rel in (data.get("subdirs") or {}).items()}
    return Paths(data_root=data_root, subdirs=subdirs)


def load_symbols(config_dir: Path | None = None, enabled_only: bool = True) -> list[Symbol]:
    """종목 목록을 읽는다.

    입력: config_dir, enabled_only (True면 enabled 종목만)
    출력: Symbol 리스트 (파일에 적힌 순서)
    검증: 종목코드는 6자리 숫자 문자열, 중복 금지, 활성 종목 수 ≤ max_symbols (< 10)
    """
    data = _read_yaml("symbols.yaml", config_dir)
    max_symbols = int(data.get("max_symbols", 9))
    if not 1 <= max_symbols < 10:
        raise ConfigError(f"max_symbols 는 1 이상 10 미만이어야 합니다: {max_symbols}")

    symbols: list[Symbol] = []
    seen: set[str] = set()
    for item in data.get("symbols") or []:
        code = item.get("code")
        if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
            raise ConfigError(f"종목코드는 6자리 숫자 문자열이어야 합니다 (따옴표 필요): {code!r}")
        if code in seen:
            raise ConfigError(f"종목코드가 중복되었습니다: {code}")
        seen.add(code)
        symbols.append(
            Symbol(
                code=code,
                name=str(item.get("name", "")),
                market=str(item.get("market", "")),
                enabled=bool(item.get("enabled", True)),
            )
        )

    enabled = [s for s in symbols if s.enabled]
    if len(enabled) > max_symbols:
        raise ConfigError(f"활성 종목 수 {len(enabled)} 가 max_symbols {max_symbols} 를 넘습니다")
    return enabled if enabled_only else symbols


def load_costs(config_dir: Path | None = None) -> Costs:
    """비용 모델을 읽는다.

    입력: config_dir
    출력: Costs (비율은 소수, 호가단위는 원)
    검증: 비율은 0 이상 1 미만, 호가단위 표는 below 오름차순이고 마지막 구간만 below=None
    """
    data = _read_yaml("costs.yaml", config_dir)
    try:
        costs = Costs(
            sell_tax_rate=float(data["sell_tax_rate"]),
            commission_rate=float(data["commission_rate"]),
            slippage_ticks=int(data["slippage_ticks"]),
            price_limit_rate=float(data["price_limit_rate"]),
            tick_size_table=tuple(
                TickBand(below=None if b["below"] is None else int(b["below"]), tick=int(b["tick"]))
                for b in data["tick_size_table"]
            ),
        )
    except KeyError as e:
        raise ConfigError(f"costs.yaml 에 필수 항목이 없습니다: {e}") from e

    for name in ("sell_tax_rate", "commission_rate", "price_limit_rate"):
        value = getattr(costs, name)
        if not 0 <= value < 1:
            raise ConfigError(f"{name} 는 0 이상 1 미만이어야 합니다: {value}")
    if costs.slippage_ticks < 0:
        raise ConfigError(f"slippage_ticks 는 0 이상이어야 합니다: {costs.slippage_ticks}")

    table = costs.tick_size_table
    if not table or table[-1].below is not None:
        raise ConfigError("tick_size_table 의 마지막 구간은 below: null 이어야 합니다")
    bounds = [b.below for b in table[:-1]]
    if any(b is None for b in bounds) or bounds != sorted(set(bounds)):  # type: ignore[type-var]
        raise ConfigError("tick_size_table 의 below 는 중복 없이 오름차순이어야 합니다")
    if any(b.tick <= 0 for b in table):
        raise ConfigError("tick_size_table 의 tick 은 양수여야 합니다")
    return costs


def load_risk_limits(config_dir: Path | None = None) -> RiskLimits:
    """리스크 한도를 읽는다.

    입력: config_dir
    출력: RiskLimits (비율은 소수, 시각은 KST "HH:MM")
    검증: 필수 항목 존재, 한도 값은 양수, 비중은 (0, 1] 범위
    """
    data = _read_yaml("risk_limits.yaml", config_dir)
    try:
        limits = RiskLimits(
            daily_loss_limit_rate=float(data["daily_loss_limit_rate"]),
            max_trades_per_day=int(data["max_trades_per_day"]),
            max_consecutive_losses=int(data["max_consecutive_losses"]),
            max_concurrent_positions=int(data["max_concurrent_positions"]),
            max_weight_per_symbol=float(data["max_weight_per_symbol"]),
            max_weight_per_sector=float(data["max_weight_per_sector"]),
            force_close_time=str(data["force_close_time"]),
            kill_switch_file=str(data["kill_switch_file"]),
        )
    except KeyError as e:
        raise ConfigError(f"risk_limits.yaml 에 필수 항목이 없습니다: {e}") from e

    if not 0 < limits.daily_loss_limit_rate < 1:
        raise ConfigError(f"daily_loss_limit_rate 는 0 초과 1 미만이어야 합니다: {limits.daily_loss_limit_rate}")
    for name in ("max_trades_per_day", "max_consecutive_losses", "max_concurrent_positions"):
        if getattr(limits, name) < 1:
            raise ConfigError(f"{name} 는 1 이상이어야 합니다: {getattr(limits, name)}")
    for name in ("max_weight_per_symbol", "max_weight_per_sector"):
        if not 0 < getattr(limits, name) <= 1:
            raise ConfigError(f"{name} 는 0 초과 1 이하여야 합니다: {getattr(limits, name)}")
    hh, sep, mm = limits.force_close_time.partition(":")
    if not (sep and hh.isdigit() and mm.isdigit() and 0 <= int(hh) < 24 and 0 <= int(mm) < 60):
        raise ConfigError(f"force_close_time 은 'HH:MM' 형식이어야 합니다: {limits.force_close_time}")
    if not limits.kill_switch_file:
        raise ConfigError("kill_switch_file 이 비어 있습니다")
    return limits


def load_trading_mode(config_dir: Path | None = None) -> str:
    """실전/모의 모드를 읽는다.

    입력: config_dir
    출력: "paper" 또는 "live". mode 항목이 없으면 "paper".
    알 수 없는 값이면 실전으로 해석하지 않고 ConfigError를 낸다.
    """
    data = _read_yaml("trading_mode.yaml", config_dir)
    mode = data.get("mode", PAPER)
    if not isinstance(mode, str) or mode.strip().lower() not in _TRADING_MODES:
        raise ConfigError(f"mode 는 'paper' 또는 'live' 여야 합니다: {mode!r}")
    return mode.strip().lower()


def is_live(config_dir: Path | None = None) -> bool:
    """실전 모드이면 True. 실전 전용 동작 앞에서는 반드시 이 함수로 명시적으로 확인한다."""
    return load_trading_mode(config_dir) == LIVE
