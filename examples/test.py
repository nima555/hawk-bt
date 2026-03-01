"""
Hawk Trading Strategy v1: Adaptive Mean Reversion
===================================================
レンジ相場向け。Bollinger Band + RSI で平均回帰エントリー。
ATR ベースの動的 TP/SL。
"""
import numpy as np
import requests
from hawk_bt import Strategy, Context, HawkEngine, configure_logging

# ── 設定 ──
API = "http://127.0.0.1:8000/v1"
AUTH = {"Authorization": "Bearer hawk_abca0b0eef9b754d0cf5e0e6f5f95a53034f61476a9227eb13cb7a5c78a6c055"}
DATASET_ID = 101
ITERATION = 1


class MeanReversionV1(Strategy):
    """Bollinger Band + RSI ミーンリバージョン戦略"""

    def __init__(self, bb_period=20, bb_k=2.0, rsi_period=14,
                 rsi_oversold=30, rsi_overbought=70,
                 atr_period=14, tp_mult=2.0, sl_mult=1.0, units=10):
        self.bb_period = bb_period
        self.bb_k = bb_k
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_period = atr_period
        self.tp_mult = tp_mult
        self.sl_mult = sl_mult
        self.units = units

    def _rsi(self, closes):
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = gains[-self.rsi_period:].mean()
        avg_loss = losses[-self.rsi_period:].mean()
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _atr(self, highs, lows, closes):
        n = self.atr_period
        tr_list = []
        for j in range(1, n + 1):
            idx = -(n + 1) + j
            h = highs[idx]
            l = lows[idx]
            pc = closes[idx - 1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)
        return np.mean(tr_list)

    async def step(self, ctx: Context):
        i = ctx.state.snapshot.step
        min_bars = max(self.bb_period, self.rsi_period, self.atr_period) + 5
        if i < min_bars:
            return

        close = ctx.state.candles.close[:i]
        high = ctx.state.candles.high[:i]
        low = ctx.state.candles.low[:i]
        price = ctx.state.snapshot.price

        # Bollinger Bands
        sma = close[-self.bb_period:].mean()
        std = close[-self.bb_period:].std()
        if std == 0:
            return
        upper = sma + self.bb_k * std
        lower = sma - self.bb_k * std

        # RSI
        rsi = self._rsi(close)

        # ATR
        atr = self._atr(high, low, close)
        if atr <= 0:
            return

        tp = atr * self.tp_mult
        sl = atr * self.sl_mult

        # ポジションが無い場合のみエントリー
        if ctx.state.snapshot.tickets_num == 0:
            if price < lower and rsi < self.rsi_oversold:
                await ctx.engine.place_ticket(
                    side="buy", units=self.units,
                    take_profit=tp, stop_loss=sl,
                )
            elif price > upper and rsi > self.rsi_overbought:
                await ctx.engine.place_ticket(
                    side="sell", units=self.units,
                    take_profit=tp, stop_loss=sl,
                )


def main():
    configure_logging(2)

    sid = None  # on_result クロージャ用

    # 1. on_result: シミュレーション完了時に結果を API に保存
    def on_result(result):
        analysis = result.to_analysis()
        print(f"\n{'='*50}")
        print(f"Steps:          {result.steps}")
        print(f"Final Balance:  {result.final_balance():.2f}")
        print(f"Total Return:   {analysis['outcome']['totalReturn']:.2%}")
        print(f"Max Drawdown:   {analysis['outcome']['maxDrawdown']:.2%}")
        print(f"Profit Factor:  {analysis['attribution']['profitFactor']}")
        print(f"Win Rate:       {analysis['attribution']['winRate']}")
        print(f"Total Orders:   {analysis['action']['totalOrders']}")
        print(f"{'='*50}\n")

        if sid:
            resp = requests.post(
                f"{API}/backtests/{sid}/complete",
                headers=AUTH, json={"analysis": analysis},
            )
            print(f"Result saved: {resp.status_code}")

    # 2. エンジンをバックグラウンドで起動（WSサーバーを先に立てる）
    engine = HawkEngine(
        host="127.0.0.1", port=8787,
        on_result=on_result,
        single_run=True,
    )
    thread = engine.start_background(MeanReversionV1())
    if not engine.wait_ready(timeout=10):
        print("ERROR: Engine failed to start within 10s")
        return
    print("Engine listening on ws://127.0.0.1:8787")

    # 3. セッション登録（エンジン起動後なのでAPIの接続チェックが通る）
    resp = requests.post(f"{API}/backtests", headers=AUTH, json={
        "dataset_id": DATASET_ID,
        "iteration": ITERATION,
        "strategy_note": "v1: BB(20,2) + RSI(14, 30/70) mean reversion, ATR-based TP(2x)/SL(1x)",
        "seed": 42,
        "config": {},
        "ws_url": "ws://127.0.0.1:8787",
    })
    if resp.status_code != 201:
        print(f"ERROR: Session creation failed: {resp.status_code} {resp.text}")
        return
    session = resp.json()
    sid = session["session_id"]
    print(f"Session registered: {sid}")

    # 4. シミュレーション完了を待つ
    thread.join()


if __name__ == "__main__":
    main()
