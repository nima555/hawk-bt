# py_engine — Hawk Trading Simulator Python Client

ブラウザ上の WASM トレーディングエンジンを Python から操作するクライアントライブラリ。
自動売買戦略の開発・バックテスト・ライブ検証に使う。

## Architecture

```
Browser (WASM Engine + UI)
    ↕  WebSocket (binary, lock-step RPC)
py_engine (Python)
    ↕  py_engine_rust (Rust extension, required)
```

- **WASM エンジン**: 為替シミュレーションの本体。ブラウザ内で動作する
- **py_engine**: Python 側のクライアント。戦略ロジックの実行、RPC 通信、状態管理を担当
- **py_engine_rust**: バイナリコーデック（encode/decode）と高速 WS サーバの Rust 実装。必須依存

## Requirements

- Python >= 3.10
- `py-engine-rust` (Rust extension, **必須**)
- `numpy >= 1.23`
- `websockets >= 11`

```bash
pip install -e .
```

## Quick Start

```python
import asyncio
from py_engine.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter
from py_engine.runtime.engine_api import EngineAPI, BoundEngine
from py_engine.runtime.loop import run_attached, create_progress_printer
from py_engine.strategy.api import Strategy, Context

class MyStrategy(Strategy):
    async def step(self, ctx: Context) -> None:
        s = ctx.state.statics
        price = s.current_rate

        if price > 100.0 and s.tickets_num == 0:
            await ctx.engine.place_ticket(side="buy", units=10, sub_limit_pips=5.0, stop_order_pips=3.0)

async def main():
    engine = RustEngineAsyncAdapter(host="127.0.0.1", port=8787)
    await engine.start()
    await engine.wait_connected(timeout=None)

    result = await run_attached(engine, MyStrategy(), gate_policy="eager")
    print(f"Steps: {result.steps}, Final assets: {result.final_assets()}")

asyncio.run(main())
```

## What You Can Do

### 1. Strategy を書く

`Strategy` を継承して `step()` を実装するだけ。毎ステップ自動で呼ばれる。

```python
class Strategy(ABC):
    @abstractmethod
    async def step(self, ctx: Context) -> None: ...
```

`ctx` から得られるもの:
- `ctx.state.statics` — 現在の資産・価格・ポジション情報 (`Statics`)
- `ctx.engine` — エンジン操作 (`BoundEngine`)
- `ctx.state.done` — シミュレーション終了フラグ
- `ctx.user` — 自由に使える `dict`（状態保持・ログ等）

### 2. トレード操作

#### 即時エントリー (place_ticket)

```python
out = await ctx.engine.place_ticket(
    side="buy",           # "buy" | "sell"
    units=100,            # ロット数
    sub_limit_pips=5.0,   # TP (利確幅、絶対価格差)  ※省略可
    stop_order_pips=3.0,  # SL (損切幅、絶対価格差)  ※省略可
    trail_pips=2.0,       # トレーリングストップ     ※省略可
)
# out: shape (14,) — [0]=flag(チケットID), [1..4]=reward系, [5]=current_rate, ...
```

#### 予約注文 (place_token)

```python
out = await ctx.engine.place_token(
    side="sell",          # "buy" | "sell"
    order="limit",        # "limit" | "stop"
    price=90.0,           # 発注価格
    units=80,
    sub_limit_pips=8.0,   # TP  ※省略可
    stop_order_pips=25.0, # SL  ※省略可
    trail_pips=None,      # トレーリング ※省略可
    time_limits=240.0,    # 有効時間（ステップ数） ※省略可
)
# out: shape (18,) — [0]=flag(トークンID), ...
```

#### 決済 (close_step)

```python
events = await ctx.engine.close_step(
    flags=[ticket_flag],  # 対象チケットのflag(ID)
    actions=[1],          # 1=全決済, 2=部分決済(REDUCE)
    ratios=[0.0],         # action=2 のとき決済比率 (0.0〜1.0)
)
# events: shape (N, 5) — 決済結果
```

複数チケットの一括決済も可能（配列で渡す）。

### 3. 市場情報の取得

```python
# 最新状態
statics = await ctx.engine.get_statics()
statics.assets           # 資産
statics.virtual_assets   # 含み損益込み資産
statics.current_rate     # 現在価格
statics.current_step     # 現在ステップ
statics.total_steps      # 総ステップ数
statics.margin_ratio     # 証拠金維持率
statics.tickets_num      # オープンチケット数
statics.token_num        # 予約注文数
# ...他 20 フィールド

# チケット一覧
tickets = await ctx.engine.get_ticket_list()
# shape (rows, cols) — 各行が1チケットの詳細
```

### 4. シミュレーション実行

#### Attached モード（ブラウザ主導）

ブラウザ側で OHLC データが投入済みの前提で、Python は戦略の実行だけを行う。

```python
result = await run_attached(engine, strategy, gate_policy="eager")
```

#### Backtest モード（Python 主導）

Python から OHLC データを送信してバックテストを実行する。

```python
result = await run_backtest(engine, strategy, ohlc5, steps=5000)
```

`ohlc5`: `np.ndarray` shape `(N, 5)` — `[time_ms, open, close, high, low]`

#### BacktestResult

```python
result.steps              # 実行ステップ数
result.assets             # np.ndarray — ステップごとの資産推移
result.virtual_assets     # np.ndarray — 含み損益込み資産推移
result.price              # np.ndarray — 価格推移
result.final_assets()     # 最終資産
result.max_drawdown()     # 最大ドローダウン (負の値)
```

### 5. 接続バックエンド

3つの接続方式から選べる:

| 方式 | 速度 | 用途 |
|------|------|------|
| `RustEngineAsyncAdapter` | 最速 | 推奨。Rust で WS + RPC + codec を一貫処理 |
| `RustWsServerRpc` + `EngineAPI` | 速い | Rust WS サーバ + Python RPC 層 |
| `WsServer` + `RpcClient` + `EngineAPI` | 標準 | Full Python。トークン認証・Origin 検証あり |

```python
# 推奨: RustEngineAsyncAdapter
engine = RustEngineAsyncAdapter(host="127.0.0.1", port=8787)
await engine.start()
await engine.wait_connected()

# Python WS Server
server = WsServer(host="127.0.0.1", port=8787, token=WsServer.generate_token())
await server.start()
ws = await server.wait_connected()
rpc = RpcClient(ws)
engine = EngineAPI(rpc)
```

### 6. Gate Policy

ステップ内の整合性同期モード。ブラウザ側のUIで設定するか、`get_gate_policy_hint()` で自動取得する。

- **`eager`** (デフォルト): 毎操作で `affect` + `get_statics` を実行。正確だが遅い
- **`step_end`**: ステップ終了時のみ同期。高速だが中間状態は古い可能性がある

```python
gate_policy = await engine.get_gate_policy_hint() or "eager"
result = await run_attached(engine, strategy, gate_policy=gate_policy)
```

## Responsibility Split

### py_engine が担当すること

- WebSocket 接続管理（サーバ起動、接続待ち、切断検知）
- バイナリプロトコルの encode/decode（Rust 実装）
- RPC 通信（送信 → 応答待ち、タイムアウト、エラーハンドリング）
- ステップループの制御（`run_attached` / `run_backtest`）
- 状態の自動同期（`BoundEngine` が `affect` → `get_statics` を自動実行）
- 終端検出（破産 `GAME_BREAK` / 終了 `GAME_END`）
- 入力バリデーション（side/order/units/ratios の型・範囲チェック）
- 進捗表示（`create_progress_printer`）

### ユーザーが担当すること

- **戦略ロジック**: いつ・何を・どれだけ売買するかの判断
- **パラメータ設計**: TP/SL 幅、ロット数、エントリー条件
- **リスク管理**: 最大ポジション数、証拠金維持率の監視、ドローダウン制限
- **OHLC データの用意**: backtest モードでは `(N, 5)` の numpy 配列を自分で用意する
- **結果の分析**: `BacktestResult` の解釈、パフォーマンス評価
- **ブラウザ側の起動**: WASM エンジンを含むブラウザ UI を事前に開いておく

### py_engine がやらないこと

- 戦略の推奨や最適化
- リスクの自動制限（ユーザーが `step()` 内で判断する）
- OHLC データの取得・前処理
- ブラウザ側の WASM エンジン管理

## TP/SL の仕様

- TP/SL 値は**絶対価格差**（pips やパーセントではない）
- Buy の場合: TP ヒット = `high >= open_rate + sub_limit_pips`
- Buy の場合: SL ヒット = `low <= open_rate - stop_order_pips`
- 同一バーで TP と SL の両方がヒットした場合: **SL が優先**
- 決済価格はバーの close 価格（正確な TP/SL 水準ではない）

## Project Structure

```
py_engine/
├── src/py_engine/
│   ├── protocol/
│   │   └── wire.py          # バイナリプロトコル定数・pack/unpack
│   ├── runtime/
│   │   ├── engine_api.py     # EngineAPI, BoundEngine, Statics, FN
│   │   ├── loop.py           # run_backtest, run_attached, BacktestResult
│   │   ├── rpc_client.py     # RpcClient (Python WS用)
│   │   ├── ws_server.py      # WsServer (Python WS用, Origin/Token認証)
│   │   ├── rust_ws_server.py # RustWsServerRpc (Rust WSサーバラッパ)
│   │   ├── rust_engine_async_adapter.py  # RustEngineAsyncAdapter (推奨)
│   │   └── progress.py       # 進捗バー
│   ├── strategy/
│   │   └── api.py            # Strategy, Context, EngineState, Engine protocol
│   └── results/              # (拡張用)
├── examples/
│   └── simple_ma.py          # MA クロスオーバー戦略のサンプル
└── pyproject.toml
```
