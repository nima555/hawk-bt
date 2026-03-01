from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional, Callable, Union

import numpy as np

from hawk_backtester.runtime.engine_api import Snapshot, Engine
from hawk_backtester.strategy.api import Strategy, Context, SessionState, Candles
from .progress import create_progress_printer
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------
@dataclass
class BacktestResult:
    """Container for backtest output arrays."""
    steps: int
    balance: np.ndarray
    equity: np.ndarray
    price: np.ndarray
    total_orders: int = 0
    win_count: int = 0
    loss_count: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    def final_balance(self) -> float:
        return float(self.balance[-1])

    def max_drawdown(self) -> float:
        peak = np.maximum.accumulate(self.balance)
        dd = (self.balance - peak) / peak
        return float(dd.min())

    def max_drawdown_before_end(self) -> float:
        b = self.balance
        valid = b[b > 0]
        if valid.size == 0:
            return -1.0
        peak = np.maximum.accumulate(valid)
        dd = (valid - peak) / peak
        return float(dd.min())

    def to_analysis(self) -> dict:
        """Generate analysis dict compatible with Agent Mode API.

        Computes outcome, attribution, and action metrics from the
        balance/equity arrays and trade statistics collected during
        the simulation loop.
        """
        ib = float(self.balance[0]) if self.steps > 0 else 0.0
        fb = self.final_balance() if self.steps > 0 else 0.0
        eq = float(self.equity[-1]) if self.steps > 0 else 0.0
        total_return = (eq - ib) / ib if ib else 0.0
        mdd = self.max_drawdown() if self.steps > 0 else 0.0

        pf = None
        wr = None
        if self.total_orders > 0:
            closed = self.win_count + self.loss_count
            wr = self.win_count / closed if closed > 0 else None
            pf = (self.gross_profit / self.gross_loss
                  if self.gross_loss > 0 else None)

        return {
            'outcome': {
                'totalSteps': self.steps,
                'endingAssets': fb,
                'endingEquity': eq,
                'totalReturn': total_return,
                'maxDrawdown': mdd,
                'returnOverMaxDD': (
                    total_return / abs(mdd) if mdd != 0 else 0.0
                ),
            },
            'attribution': {
                'profitFactor': pf,
                'winRate': wr,
                'winCount': self.win_count,
                'lossCount': self.loss_count,
            },
            'action': {
                'totalOrders': self.total_orders,
            },
        }


# ---------------------------------------------------------------------------
# Progress helpers
# ---------------------------------------------------------------------------
ProgressCallback = Callable[[int, Optional[int]], None]


def _create_log_progress(interval: int = 500) -> ProgressCallback:
    """Log-based progress reporter for non-TTY environments."""
    state = {"last": 0}

    def _reporter(done: int, total: Optional[int]) -> None:
        if not total:
            return
        if done - state["last"] >= interval or done >= total:
            logger.info("Progress: %d/%d (%.1f%%)", done, total, done / total * 100)
            state["last"] = done

    return _reporter


def _resolve_progress(progress: Union[bool, ProgressCallback, None]) -> Optional[ProgressCallback]:
    """Turn the user-facing ``progress`` argument into a concrete callback."""
    if progress is None or progress is False:
        return None
    if callable(progress):
        return progress
    # progress=True  →  auto-detect TTY
    if sys.stdout.isatty():
        return create_progress_printer()
    return _create_log_progress()


# ---------------------------------------------------------------------------
# Main loops
# ---------------------------------------------------------------------------
async def run_backtest(
    engine,
    strategy: Strategy,
    ohlc5: np.ndarray,
    *,
    steps: Optional[int] = None,
    gate_policy: str = "eager",
    progress: Union[bool, ProgressCallback] = True,
) -> BacktestResult:
    """Run a full backtest by sending candle data to the engine.

    The engine receives OHLC data via ``init_candles``, then loops
    ``get_snapshot → strategy.step → step_next`` for each bar.
    """
    if not isinstance(ohlc5, np.ndarray):
        raise TypeError("ohlc5 must be numpy.ndarray")
    ohlc5 = np.asarray(ohlc5, dtype=np.float64, order="C")

    if ohlc5.ndim != 2 or ohlc5.shape[1] != 5:
        raise ValueError(f"ohlc5 must be shape (N,5), got {ohlc5.shape}")

    total_steps = ohlc5.shape[0] if steps is None else int(steps)
    if total_steps <= 0:
        raise ValueError("steps must be positive")

    progress_fn = _resolve_progress(progress)

    # Engine init
    await engine.init_candles(ohlc5)

    s0 = await engine.get_snapshot()
    candles = Candles.from_matrix(ohlc5)
    state = SessionState(snapshot=s0, candles=candles)
    eng = Engine(engine, state, refresh_after_reads=True, gate_policy=gate_policy)
    ctx = Context(engine=eng, state=state)

    balance = np.empty(total_steps, dtype=np.float64)
    equity = np.empty(total_steps, dtype=np.float64)
    price = np.empty(total_steps, dtype=np.float64)

    # Trade tracking
    prev_ticket_all: float = s0.ticket_all_num
    prev_tickets: float = s0.tickets_num
    prev_balance: float = s0.balance
    total_orders = 0
    win_count = 0
    loss_count = 0
    gross_profit = 0.0
    gross_loss = 0.0

    logger.info("Backtest started: %d steps, gate_policy=%s", total_steps, gate_policy)
    filled = 0

    for t in range(total_steps):
        if ctx.state.done:
            break

        snap: Snapshot = await ctx.engine.get_snapshot()
        ctx.state.snapshot = snap

        balance[t] = snap.balance
        equity[t] = snap.equity
        price[t] = snap.price

        filled += 1

        # Track new orders
        new_orders = int(snap.ticket_all_num - prev_ticket_all)
        if new_orders > 0:
            total_orders += new_orders
            prev_ticket_all = snap.ticket_all_num

        # Track closed positions
        closed_count = int(prev_tickets - snap.tickets_num)
        if closed_count > 0 and snap.tickets_num < prev_tickets:
            pnl = snap.balance - prev_balance
            if pnl > 0:
                win_count += closed_count
                gross_profit += pnl
            elif pnl < 0:
                loss_count += closed_count
                gross_loss += abs(pnl)
        prev_tickets = snap.tickets_num
        prev_balance = snap.balance

        await strategy.step(ctx)
        await ctx.engine.step_next()

        if progress_fn:
            try:
                progress_fn(filled, total_steps)
            except Exception:
                logger.exception("progress callback failed")

    # Return only the filled portion (copy for safety)
    balance = balance[:filled].copy()
    equity = equity[:filled].copy()
    price = price[:filled].copy()

    logger.info("Backtest completed: %d steps", filled)

    return BacktestResult(
        steps=filled,
        balance=balance,
        equity=equity,
        price=price,
        total_orders=total_orders,
        win_count=win_count,
        loss_count=loss_count,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
    )


async def run_attached(
    engine,
    strategy: Strategy,
    *,
    steps: Optional[int] = None,
    gate_policy: str = "eager",
    progress: Union[bool, ProgressCallback] = True,
) -> BacktestResult:
    """Run a backtest against a browser-initialized engine.

    Assumes the browser has already loaded candle data.  Loops
    ``get_snapshot → strategy.step → step_next`` until the session ends
    or the step limit is reached.
    """
    total_steps = None if steps is None else int(steps)
    if total_steps is not None and total_steps <= 0:
        raise ValueError("steps must be positive")

    progress_fn = _resolve_progress(progress)

    s0 = await engine.get_snapshot()

    # Fetch OHLC data once at simulation start
    candles: Candles | None = None
    try:
        ohlc_raw = await engine.get_ohlc(timeout=10.0)
        candles = Candles.from_matrix(ohlc_raw)
        logger.debug("OHLC loaded: %d bars", len(candles.time))
    except Exception:
        logger.warning("Could not fetch OHLC data")

    state = SessionState(snapshot=s0, candles=candles)
    eng = Engine(engine, state, refresh_after_reads=True, gate_policy=gate_policy)
    ctx = Context(engine=eng, state=state)

    balance_list: list[float] = []
    equity_list: list[float] = []
    price_list: list[float] = []

    # Trade tracking: detect closed positions by watching ticket_all_num
    # and balance changes when positions close.
    prev_ticket_all: float = s0.ticket_all_num
    prev_tickets: float = s0.tickets_num
    prev_balance: float = s0.balance
    total_orders = 0
    win_count = 0
    loss_count = 0
    gross_profit = 0.0
    gross_loss = 0.0

    def _notify_progress() -> None:
        if not progress_fn:
            return
        total_hint = ctx.state.snapshot.total_steps or total_steps
        try:
            progress_fn(len(balance_list), total_hint if total_hint else None)
        except Exception:
            logger.exception("progress callback failed")

    while True:
        if ctx.state.done:
            break

        if total_steps is not None and len(balance_list) >= total_steps:
            break

        snap: Snapshot = await ctx.engine.get_snapshot()
        ctx.state.snapshot = snap

        balance_list.append(snap.balance)
        equity_list.append(snap.equity)
        price_list.append(snap.price)

        # Track new orders (cumulative ticket counter increased)
        new_orders = int(snap.ticket_all_num - prev_ticket_all)
        if new_orders > 0:
            total_orders += new_orders
            prev_ticket_all = snap.ticket_all_num

        # Track closed positions: ticket count decreased AND balance changed
        closed_count = int(prev_tickets - snap.tickets_num)
        if closed_count > 0 and snap.tickets_num < prev_tickets:
            pnl = snap.balance - prev_balance
            if pnl > 0:
                win_count += closed_count
                gross_profit += pnl
            elif pnl < 0:
                loss_count += closed_count
                gross_loss += abs(pnl)
            # pnl == 0: break-even, count as neither win nor loss
        prev_tickets = snap.tickets_num
        prev_balance = snap.balance

        await strategy.step(ctx)
        await ctx.engine.step_next()
        _notify_progress()

    balance_arr = np.asarray(balance_list, dtype=np.float64)
    equity_arr = np.asarray(equity_list, dtype=np.float64)
    price_arr = np.asarray(price_list, dtype=np.float64)
    filled = balance_arr.size

    if ctx.state.done:
        logger.info(
            "Simulation finished: %d steps (exit_code=%s)",
            filled,
            ctx.state.exit_code,
        )

    return BacktestResult(
        steps=filled,
        balance=balance_arr,
        equity=equity_arr,
        price=price_arr,
        total_orders=total_orders,
        win_count=win_count,
        loss_count=loss_count,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
    )
