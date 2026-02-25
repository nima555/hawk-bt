from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Callable

import numpy as np

from py_engine.runtime.engine_api import EngineAPI, Statics, BoundEngine
from py_engine.strategy.api import Strategy, Context, EngineState
from .progress import create_progress_printer
import logging

logger = logging.getLogger(__name__)


# -------------------------
# Main loop
# -------------------------
async def run_backtest(
    engine: EngineAPI,
    strategy: Strategy,
    ohlc5: np.ndarray,
    *,
    steps: Optional[int] = None,
    gate_policy: str = "eager",
) -> BacktestResult:
    """
    逐次バックテストループ（return廃止版）。

    仕様:
    - ctx.state.statics が唯一の真実（常に最新）
    - ループも Strategy も engine 操作は ctx.engine(BoundEngine) 経由に統一
    """

    if not isinstance(ohlc5, np.ndarray):
        raise TypeError("ohlc5 must be numpy.ndarray")
    ohlc5 = np.asarray(ohlc5, dtype=np.float64, order="C")

    if ohlc5.ndim != 2 or ohlc5.shape[1] != 5:
        raise ValueError(f"ohlc5 must be shape (N,5), got {ohlc5.shape}")

    total_steps = ohlc5.shape[0] if steps is None else int(steps)
    if total_steps <= 0:
        raise ValueError("steps must be positive")

    # -------------------------
    # Engine init
    # -------------------------
    await engine.init_ohlc5(ohlc5)

    # 初期statics
    s0 = await engine.get_statics()
    state = EngineState(statics=s0)
    bound = BoundEngine(engine, state, refresh_after_reads=True, gate_policy=gate_policy)
    ctx = Context(engine=bound, state=state)

    assets = np.empty(total_steps, dtype=np.float64)
    virtual_assets = np.empty(total_steps, dtype=np.float64)
    price = np.empty(total_steps, dtype=np.float64)

    filled = 0

    for t in range(total_steps):
        if ctx.state.done:
            break

        # statics を更新（この行はあなたの実装に合わせて）
        statics: Statics = await ctx.engine.get_statics()
        ctx.state.statics = statics

        assets[t] = statics.assets
        virtual_assets[t] = statics.virtual_assets
        price[t] = statics.current_rate

        filled += 1

        await strategy.step(ctx)
        await ctx.engine.step_next()

    # ★有効部分だけ返す（copy推奨：後段で安全）
    assets = assets[:filled].copy()
    virtual_assets = virtual_assets[:filled].copy()
    price = price[:filled].copy()

    return BacktestResult(
        steps=filled,
        assets=assets,
        virtual_assets=virtual_assets,
        price=price,
    )


@dataclass
class BacktestResult:
    steps: int
    assets: np.ndarray
    virtual_assets: np.ndarray
    price: np.ndarray

    def final_assets(self) -> float:
        return float(self.assets[-1])

    def max_drawdown(self) -> float:
        peak = np.maximum.accumulate(self.assets)
        dd = (self.assets - peak) / peak
        return float(dd.min())
    
    def max_drawdown_before_end(self) -> float:
        a = self.assets
        # 0 になる直前まで使う
        valid = a[a > 0]
        if valid.size == 0:
            return -1.0
        peak = np.maximum.accumulate(valid)
        dd = (valid - peak) / peak
        return float(dd.min())


ProgressCallback = Callable[[int, Optional[int]], None]


async def run_attached(
    engine: EngineAPI,
    strategy: Strategy,
    *,
    steps: Optional[int] = None,
    gate_policy: str = "eager",
    progress_callback: Optional[ProgressCallback] = None,
) -> BacktestResult:
    """
    INIT(100) を Python から送らない版（return廃止版）。

    ＝ブラウザ側で既に INIT/データ投入が済んでいる前提で、
      get_statics → step(ctx) → step_next を回すだけ。
    """
    total_steps = None if steps is None else int(steps)
    if total_steps is not None and total_steps <= 0:
        raise ValueError("steps must be positive")

    s0 = await engine.get_statics()
    state = EngineState(statics=s0)
    bound = BoundEngine(engine, state, refresh_after_reads=True, gate_policy=gate_policy)
    ctx = Context(engine=bound, state=state)

    assets: list[float] = []
    virtual_assets: list[float] = []
    price: list[float] = []

    def _notify_progress() -> None:
        if not progress_callback:
            return
        total_hint = ctx.state.statics.total_steps or total_steps
        try:
            progress_callback(len(assets), total_hint if total_hint else None)
        except Exception:
            logger.exception("progress_callback failed")

    while True:
        if ctx.state.done:
            break

        if total_steps is not None and len(assets) >= total_steps:
            break

        # statics を更新（この行はあなたの実装に合わせて）
        statics: Statics = await ctx.engine.get_statics()
        ctx.state.statics = statics

        assets.append(statics.assets)
        virtual_assets.append(statics.virtual_assets)
        price.append(statics.current_rate)

        await strategy.step(ctx)
        await ctx.engine.step_next()
        _notify_progress()

    assets_arr = np.asarray(assets, dtype=np.float64)
    virtual_assets_arr = np.asarray(virtual_assets, dtype=np.float64)
    price_arr = np.asarray(price, dtype=np.float64)
    filled = assets_arr.size

    if ctx.state.done:
        logger.info(
            "[run_attached] simulation finished after %d steps (done_code=%s)",
            filled,
            ctx.state.done_code,
        )
    _notify_progress()

    return BacktestResult(
        steps=filled,
        assets=assets_arr,
        virtual_assets=virtual_assets_arr,
        price=price_arr,
    )
