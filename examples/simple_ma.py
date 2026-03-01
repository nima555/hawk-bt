"""
Moving Average Crossover Strategy
==================================
Fast SMA と Slow SMA のクロスオーバーでエントリー。
ATR ベースの TP/SL で利確・損切りを管理。

- Golden Cross (fast > slow) → Buy
- Dead Cross  (fast < slow) → Sell
- TP = ATR × tp_mult, SL = ATR × sl_mult
"""

import numpy as np
from hawk_backtester import Strategy, Context, HawkEngine, configure_logging


class MACrossoverStrategy(Strategy):
    """SMA クロスオーバー + ATR ベース TP/SL"""

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        atr_period: int = 14,
        tp_mult: float = 2.0,
        sl_mult: float = 1.0,
        units: int = 10,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.tp_mult = tp_mult
        self.sl_mult = sl_mult
        self.units = units

    async def step(self, ctx: Context) -> None:
        s = ctx.state.snapshot
        i = int(s.step or 0)
        candles = ctx.state.candles

        # ── ウォームアップ: slow_period 分のデータが溜まるまで待機 ──
        if candles is None or i < self.slow_period + 1:
            return

        close = candles.close[:i]
        high = candles.high[:i]
        low = candles.low[:i]

        # ── SMA 計算 ──
        sma_fast = close[-self.fast_period :].mean()
        sma_slow = close[-self.slow_period :].mean()

        # ── 前バーの SMA（クロス判定用） ──
        prev_fast = close[-self.fast_period - 1 : -1].mean()
        prev_slow = close[-self.slow_period - 1 : -1].mean()

        # ── ATR 計算 ──
        n = min(self.atr_period, len(close) - 1)
        tr = np.maximum(
            high[-n:] - low[-n:],
            np.maximum(
                np.abs(high[-n:] - close[-n - 1 : -1]),
                np.abs(low[-n:] - close[-n - 1 : -1]),
            ),
        )
        atr = float(tr.mean())
        if atr <= 0:
            return

        tp = atr * self.tp_mult
        sl = atr * self.sl_mult

        has_position = int(s.tickets_num or 0) > 0

        # ── クロスオーバー検出 ──
        golden_cross = prev_fast <= prev_slow and sma_fast > sma_slow
        dead_cross = prev_fast >= prev_slow and sma_fast < sma_slow

        if not golden_cross and not dead_cross:
            return

        # ── 既存ポジションがあれば全決済 ──
        if has_position:
            try:
                tickets = await ctx.engine.get_ticket_list()
                if tickets.ndim == 2 and tickets.shape[0] > 0:
                    ids = [int(tickets[j, 0]) for j in range(tickets.shape[0])]
                    await ctx.engine.close_positions(
                        position_ids=ids,
                        actions=[2] * len(ids),
                        ratios=[1.0] * len(ids),
                    )
            except Exception:
                pass

        # ── 新規エントリー ──
        side = "buy" if golden_cross else "sell"
        try:
            await ctx.engine.place_ticket(
                side=side,
                units=self.units,
                take_profit=tp,
                stop_loss=sl,
            )
        except Exception:
            pass


if __name__ == "__main__":
    configure_logging(2)
    HawkEngine(host="127.0.0.1", port=8787).start(
        MACrossoverStrategy(
            fast_period=20,
            slow_period=50,
            atr_period=14,
            tp_mult=2.0,
            sl_mult=1.0,
            units=10,
        )
    )
