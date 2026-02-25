import asyncio
import sys
import time
from pathlib import Path
from collections import deque

# Ensure repo src/ is on sys.path when running directly from examples/
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from py_engine.runtime.ws_server import WsServer
from py_engine.runtime.rpc_client import RpcClient
from py_engine.runtime.engine_api import EngineAPI
from py_engine.runtime.loop import run_attached, create_progress_printer
from py_engine.strategy.api import Strategy, Context
from py_engine.runtime.rust_ws_server import RustWsServerRpc
from py_engine.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter

# ===== Toggle: choose Rust or Python backend here =====
USE_RUST_ENGINE_ASYNC = True  # True: use RustEngineAsyncAdapter
USE_RUST_WS_SERVER = False      # Fallback: Rust WS server + Python EngineAPI
RUST_WS_HOST = "127.0.0.1"
RUST_WS_PORT = 8787


class MultiOrderStrategy(Strategy):
    """
    シンプルなデモ戦略:
      - 決め打ちのステップで複数のチケットを発行
      - 価格に対して上下に予約注文(Token)を複数仕掛ける
    """

    def __init__(self):
        # 発行するステップとサイドを固定で用意
        self.ticket_plan = {
            5: "buy",
            30: "sell",
            60: "buy",
            90: "sell",
            120: "buy",
        }
        self.token_plan = {
            15: ("buy", "limit"),
            45: ("sell", "limit"),
            75: ("buy", "stop"),
            105: ("sell", "stop"),
        }
        self._done_tickets = set()
        self._done_tokens = set()

    async def step(self, ctx: Context) -> None:
        s = ctx.state.statics
        step_idx = s.current_step
        price = s.current_rate if s.current_rate and s.current_rate > 0 else None

        # ---- 即時チケット ----
        side = self.ticket_plan.get(step_idx)
        if side and step_idx not in self._done_tickets:
            units = 100 + (step_idx % 3) * 50
            await ctx.engine.place_ticket(
                side=side,
                units=units,
                sub_limit_pips=5,
                stop_order_pips=35,
                trail_pips=10,
            )
            self._done_tickets.add(step_idx)

        # ---- 予約トークン ----
        plan = self.token_plan.get(step_idx)
        if plan and step_idx not in self._done_tokens and price:
            side_token, order = plan
            # 価格からオフセットして簡単なエントリー水準を決める
            offset = price * 0.03  # 0.3%
            if side_token == "buy":
                target_price = 90
            else:
                target_price = 90

            await ctx.engine.place_token(
                side=side_token,
                order=order,
                price=target_price,
                units=80 + (step_idx % 2) * 40,
                sub_limit_pips=8,
                stop_order_pips=25,
                trail_pips=None,
                time_limits=240,  # 4時間相当 (例)
            )
            self._done_tokens.add(step_idx)


class PriceThresholdStrategy(Strategy):
    """
    価格が 90〜91 に入ったらトークン（予約注文）を仕掛け、
    トリガーでチケット化 → 76〜77 で半分決済 → 110 以上でフルクローズする戦略（1ポジのみ）。
    """

    def __init__(
        self,
        sell_low: float = 90.0,
        sell_high: float = 91.0,
        cover_low: float = 76.0,
        cover_high: float = 77.0,
        units: int = 100,
    ):
        self.sell_low = float(sell_low)
        self.sell_high = float(sell_high)
        self.cover_low = float(cover_low)
        self.cover_high = float(cover_high)
        self.units = int(units)
        self.open_flag: int | None = None
        self.reduced_once = False

    async def step(self, ctx: Context) -> None:
        price = float(ctx.state.statics.current_rate or 0.0)
        if price <= 0:
            return

        # エントリー: 120 を超えたタイミングで売りトークンを指値で発注（1ポジのみ）
        if self.open_flag is None and price > 120.0:
            out = await ctx.engine.place_token(
                side="sell",
                order="stop",
                price=90.0,  # 90以下で約定する売り指値
                units=self.units,
                sub_limit_pips=None,
                stop_order_pips=None,
                trail_pips=None,
                time_limits=None,
            )
            try:
                # place_token は負の token_flag を返す仕様。約定後の ticket_flag はその絶対値。
                if out.ndim == 1 and out.size >= 5 and float(out[4]) == -1.0:
                    token_flag = int(out[0])
                    self.open_flag = abs(token_flag)
                    self.reduced_once = False
            except Exception:
                pass
            return

        # クローズ: まず 76〜77 で 50% リデュース、リデュース後に 110 以上でフルクローズ
        if self.open_flag is not None:
            if (not self.reduced_once) and (self.cover_low <= price <= self.cover_high):
                try:
                    await ctx.engine.close_step(
                        flags=[self.open_flag],
                        actions=[2],   # reduce
                        ratios=[0.5],  # 50% 決済
                    )
                    self.reduced_once = True
                except Exception:
                    pass  # 次回も再試行
                return

            if self.reduced_once and price >= 110.0:
                try:
                    await ctx.engine.close_step(
                        flags=[self.open_flag],
                        actions=[1],   # full close
                        ratios=[0.0],
                    )
                finally:
                    self.open_flag = None
                    self.reduced_once = False


class SimpleMAStrategy(Strategy):
    """
    SMA短期/長期のクロスオーバー戦略 (TP/SLのみで決済)

    - 短期MA > 長期MA にクロス → Buy
    - 短期MA < 長期MA にクロス → Sell
    - 決済はTP/SLヒットのみ（マニュアルclose無し）
    """

    def __init__(
        self,
        short_period: int = 10,
        long_period: int = 30,
        tp_pips: float = 5.0,
        sl_pips: float = 3.0,
        units: int = 10,
        max_open: int = 3,
        cooldown: int = 5,
    ) -> None:
        self.short_period = max(2, int(short_period))
        self.long_period = max(self.short_period + 1, int(long_period))
        self.tp_pips = float(tp_pips)
        self.sl_pips = float(sl_pips)
        self.units = max(1, int(units))
        self.max_open = max(1, int(max_open))
        self.cooldown = max(1, int(cooldown))

        self._price_hist: deque[float] = deque(maxlen=self.long_period)
        self._prev_short_ma: float | None = None
        self._prev_long_ma: float | None = None
        self._last_open_step: int = -999

    def _sma(self, n: int) -> float | None:
        if len(self._price_hist) < n:
            return None
        vals = list(self._price_hist)[-n:]
        return sum(vals) / n

    async def step(self, ctx: Context) -> None:
        s = ctx.state.statics
        step_idx = int(s.current_step or 0)
        price = float(s.current_rate or 0.0)
        if price <= 0:
            return

        self._price_hist.append(price)

        short_ma = self._sma(self.short_period)
        long_ma = self._sma(self.long_period)

        if short_ma is None or long_ma is None:
            self._prev_short_ma = short_ma
            self._prev_long_ma = long_ma
            return

        # クロスオーバー検出
        signal: str | None = None
        if self._prev_short_ma is not None and self._prev_long_ma is not None:
            prev_diff = self._prev_short_ma - self._prev_long_ma
            curr_diff = short_ma - long_ma
            if prev_diff <= 0 < curr_diff:
                signal = "buy"
            elif prev_diff >= 0 > curr_diff:
                signal = "sell"

        self._prev_short_ma = short_ma
        self._prev_long_ma = long_ma

        if signal is None:
            return

        # クールダウンチェック
        if step_idx - self._last_open_step < self.cooldown:
            return

        # エンジンの実際のオープンチケット数で制限（TP/SL自動決済を反映）
        current_open = int(s.tickets_num or 0)
        if current_open >= self.max_open:
            return

        # 新規エントリー (TP/SLのみで決済 — マニュアルclose無し)
        try:
            out = await ctx.engine.place_ticket(
                side=signal,
                units=self.units,
                sub_limit_pips=self.tp_pips,
                stop_order_pips=self.sl_pips,
                trail_pips=None,
            )
            flag = int(out[0]) if getattr(out, "size", 0) else 0
            if flag != 0:
                self._last_open_step = step_idx
        except Exception:
            pass


async def run_simulation(engine) -> None:
    strategy = SimpleMAStrategy(
        short_period=10,
        long_period=30,
        tp_pips=5.0,
        sl_pips=3.0,
        units=10,
        max_open=3,
        cooldown=5,
    )
    progress_cb = create_progress_printer()
    gate_policy = await engine.get_gate_policy_hint(timeout=5.0) or "eager"
    print(f"[py] gate_policy from UI: {gate_policy}")

    t0 = time.perf_counter()
    result = await run_attached(
        engine,
        strategy,
        gate_policy=gate_policy,
        progress_callback=progress_cb,
    )
    elapsed = time.perf_counter() - t0
    print(f"[py] simulation elapsed: {elapsed:.3f}s (gate_policy={gate_policy})")

    print(f"\n[py] simulation finished (steps={result.steps})")
    print("  final_assets:", result.final_assets())
    print("  max_drawdown:", result.max_drawdown())
    print("  assets[0..3]:", result.assets[-3:])
    print("  price[0..3]: ", result.price[:4])
    try:
        final_statics = await engine.get_statics(timeout=5.0)
        print(
            "[py] final statics:",
            f"step={final_statics.current_step}/{final_statics.total_steps}",
            f"margin_ratio={final_statics.margin_ratio}",
        )
        if final_statics.total_steps and final_statics.current_step < final_statics.total_steps:
            if final_statics.margin_ratio > 1.0:
                await engine.game_end(timeout=5.0)
    except Exception as e:
        print(f"[py] final statics fetch failed: {e}")


async def wait_for_disconnect(engine, poll_interval: float = 0.5) -> None:
    print("[py] waiting for disconnect before next run...")
    while True:
        try:
            await engine.get_gate_policy_hint(timeout=1.0)
        except Exception:
            break
        await asyncio.sleep(poll_interval)
    print("[py] disconnected. ready for next connection.\n")


async def main():
    """
    デフォルト: PythonのWSサーバ + Python RPCクライアント。
    USE_RUST_ENGINE_ASYNC=True なら RustEngineAsyncAdapter (py_engine_rust) を直接使う。
    それ以外で USE_RUST_WS_SERVER=True にすると Rust WS サーバを起動し、
    ブラウザ接続後は Rust サーバ経由で RPC を流す。
    """
    if USE_RUST_ENGINE_ASYNC:
        print(f"[py] using RustEngineAsync on ws://{RUST_WS_HOST}:{RUST_WS_PORT}")
        engine = RustEngineAsyncAdapter(host=RUST_WS_HOST, port=RUST_WS_PORT, start_seq=1)
        await engine.start()
        while True:
            print("[py] waiting browser connection...")
            await engine.wait_connected(timeout=None)
            print("[py] browser connected")
            try:
                await run_simulation(engine)
            except Exception as e:
                print(f"[py] simulation error: {e}")
            await wait_for_disconnect(engine)

    if USE_RUST_WS_SERVER:
        print(f"[py] starting Rust WS server on ws://{RUST_WS_HOST}:{RUST_WS_PORT}")

        rpc = RustWsServerRpc(host=RUST_WS_HOST, port=RUST_WS_PORT, start_seq=1)
        await rpc.start()
        while True:
            print("[py] waiting browser connection (Rust server)...")
            await rpc.wait_connected(timeout=None)
            print("[py] browser connected")

            engine = EngineAPI(rpc)
            print("[py] EngineAPI using Rust WS server backend")
            try:
                await run_simulation(engine)
            except Exception as e:
                print(f"[py] simulation error: {e}")
            await wait_for_disconnect(engine)

    # トークン認証を有効にする場合（任意）:
    #   token = WsServer.generate_token()
    #   server = WsServer(..., token=token)
    # → コンソールにトークンが表示される。UIの WS Token 欄に入力して接続。
    server = WsServer(host="127.0.0.1", port=8787, metadata={"strategy_name": "SimpleMAStrategy"})
    await server.start()
    print(f"[py] listening ws://{server.host}:{server.port}")

    while True:
        print("[py] waiting browser connection...")
        ws = await server.wait_connected(timeout=None)
        print("[py] browser connected")

        rpc = RpcClient(ws, start_seq=1)
        engine = EngineAPI(rpc)
        print("[py] EngineAPI using Python WS server backend")

        try:
            await run_simulation(engine)
        except Exception as e:
            print(f"[py] simulation error: {e}")

        print("[py] waiting for disconnect before next run...")
        try:
            await ws.wait_closed()
        except Exception:
            pass
        print("[py] disconnected. ready for next connection.\n")


if __name__ == "__main__":
    asyncio.run(main())
