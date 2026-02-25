# py_engine 詳細設計書

## 1. アーキテクチャ概要

### 1.1 レイヤー構成

```
┌─────────────────────────────────────────────────────────────┐
│                    User Layer                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Strategy (ユーザー実装)                              │    │
│  │  - step(ctx: Context) -> None                        │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Framework Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │   Context    │  │  BoundEngine │  │   EngineState    │   │
│  │  - engine    │  │  - gate管理   │  │  - statics      │   │
│  │  - state     │  │  - キャッシュ  │  │  - tickets      │   │
│  │  - user      │  │  - 終了検知   │  │  - done flag    │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Engine Layer (Rust)                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  RustEngineAsync (PyO3)                              │    │
│  │  - WebSocket Server                                  │    │
│  │  - Binary RPC Protocol                               │    │
│  │  - Encoder/Decoder                                   │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                       WebSocket (TCP)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    WASM Simulator                            │
│  (Browser / Standalone)                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. コンポーネント詳細

### 2.1 RustEngineAsync (Rust Core)

**モジュール**: `py_engine_rust`

**責務**:
- WebSocket サーバーの起動・管理
- バイナリ RPC プロトコルの実装
- Python ⇔ Rust 型変換
- 非同期 I/O (tokio)

**クラス定義**:
```rust
#[pyclass]
pub struct RustEngineAsync {
    ws: WsServer,
}

#[pymethods]
impl RustEngineAsync {
    #[new]
    fn new(host: String, port: u16, start_seq: Option<u32>) -> Self;

    fn start<'py>(&self, py: Python<'py>) -> PyResult<&'py PyAny>;
    fn wait_connected<'py>(&self, py: Python<'py>, timeout_secs: Option<f64>) -> PyResult<&'py PyAny>;
    fn init_ohlc5<'py>(&self, py: Python<'py>, ohlc5: PyReadonlyArray2<f64>, timeout_secs: Option<f64>) -> PyResult<&'py PyAny>;
    fn step_next<'py>(&self, py: Python<'py>, timeout_secs: Option<f64>) -> PyResult<&'py PyAny>;
    fn get_statics<'py>(&self, py: Python<'py>, timeout_secs: Option<f64>) -> PyResult<&'py PyAny>;
    fn get_ticket_list<'py>(&self, py: Python<'py>, timeout_secs: Option<f64>) -> PyResult<&'py PyAny>;
    fn affect<'py>(&self, py: Python<'py>, timeout_secs: Option<f64>) -> PyResult<&'py PyAny>;
    fn game_end<'py>(&self, py: Python<'py>, timeout_secs: Option<f64>) -> PyResult<&'py PyAny>;
    fn close_step<'py>(&self, py: Python<'py>, flags: PyReadonlyArray1<i32>, actions: PyReadonlyArray1<i32>, ratios: PyReadonlyArray1<f64>, timeout_secs: Option<f64>) -> PyResult<&'py PyAny>;
    fn place_token<'py>(&self, py: Python<'py>, side: String, order: String, price: f64, units: i32, ...) -> PyResult<&'py PyAny>;
    fn place_ticket<'py>(&self, py: Python<'py>, side: String, units: i32, ...) -> PyResult<&'py PyAny>;
}
```

### 2.2 WsServer (WebSocket Server)

**モジュール**: `ws.rs`

**責務**:
- TCP リスナーの管理
- WebSocket 接続の受け入れ
- ハンドシェイク（バージョン情報送信）
- メッセージ送受信

**接続ハンドシェイク**:
```json
{
  "type": "handshake",
  "python_library_version": "0.1.0"
}
```

### 2.3 Wire Protocol

**モジュール**: `wire.rs`

**ヘッダーフォーマット** (16 bytes, Little Endian):
```
Offset  Size  Field
──────────────────────────────────
0       1     protocol_version (1)
1       1     message_type
2       2     flags
4       4     sequence_number
8       2     function_id
10      2     reserved
12      4     payload_length
```

**メッセージタイプ**:
| 値 | 名前 | 方向 | 説明 |
|----|------|------|------|
| 1 | MSG_RUN | Py→WASM | コマンド送信 |
| 2 | MSG_RESULT | WASM→Py | 成功レスポンス |
| 3 | MSG_ERROR | WASM→Py | エラーレスポンス |
| 4 | MSG_PING | WASM→Py | Keep-alive |
| 5 | MSG_PONG | Py→WASM | Ping 応答 |

**ファンクション ID**:
| ID | 名前 | 説明 |
|----|------|------|
| 100 | FN_INIT | OHLC データ初期化 |
| 2 | FN_STEP_NEXT | ステップ進行 |
| 130 | FN_STEP_NEXT_AFFECT_STATICS | 複合操作 |
| 12 | FN_GET_STATICS | 統計情報取得 |
| 10 | FN_GET_TICKET_LIST | ポジション一覧 |
| 30 | FN_AFFECT | イベント実行 |
| 40 | FN_GAME_END | シミュレーション終了 |
| 31 | FN_CLOSE_STEP | ポジション決済 |
| 20 | FN_STEP_MAKE_TOKEN | 予約注文作成 |
| 21 | FN_STEP_MAKE_TICKET | 成行注文作成 |
| 120 | FN_GET_GATE_POLICY | 同期ポリシー取得 |

---

## 3. データ構造

### 3.1 Statics（統計情報）

20 要素の float64 配列:

| Index | 名前 | 型 | 説明 |
|-------|------|-----|------|
| 0 | assets | float | 現在の口座残高 |
| 1 | virtual_assets | float | 仮想残高（評価額） |
| 2 | required_margin | float | 必要証拠金 |
| 3 | margin_ratio | float | 証拠金使用率 |
| 4 | current_rate | float | 現在価格 |
| 5 | current_time_ms | float | シミュレーション時刻(ms) |
| 6 | current_step | int | 現在ステップ |
| 7 | token_num | float | アクティブ Token 数 |
| 8 | tickets_num | float | オープン Ticket 数 |
| 9 | ticket_all_num | float | 全 Ticket 数（クローズ含む） |
| 10 | count | int | 内部カウンター |
| 11-14 | ticket_stat_0..3 | float | Ticket 統計 |
| 15 | ticket_buy_count | float | 買い Ticket 総数 |
| 16 | ticket_sell_count | float | 売り Ticket 総数 |
| 17 | token_buy_count | float | 買い Token 総数 |
| 18 | token_sell_count | float | 売り Token 総数 |
| 19 | total_steps | int | 総ステップ数 |

### 3.2 OHLC5 データ形式

N×5 行列（float64）:

| Column | 名前 | 説明 |
|--------|------|------|
| 0 | time | タイムスタンプ (ms) |
| 1 | open | 始値 |
| 2 | close | 終値 |
| 3 | high | 高値 |
| 4 | low | 安値 |

### 3.3 注文パラメータ

**place_ticket() パラメータ**:
```python
place_ticket(
    side: str,                      # "buy" or "sell"
    units: int,                     # ポジションサイズ (> 0)
    sub_limit_pips: float = None,   # 利確 (pips)
    stop_order_pips: float = None,  # 損切 (pips)
    trail_pips: float = None,       # トレール (pips)
    timeout_secs: float = 10.0
) -> ndarray[14]
```

**place_token() パラメータ**:
```python
place_token(
    side: str,                      # "buy" or "sell"
    order: str,                     # "limit" or "stop"
    price: float,                   # 発注価格
    units: int,                     # ポジションサイズ (> 0)
    sub_limit_pips: float = None,   # 利確 (pips)
    stop_order_pips: float = None,  # 損切 (pips)
    trail_pips: float = None,       # トレール (pips)
    time_limits: float = None,      # 有効時間
    timeout_secs: float = 10.0
) -> ndarray[18]
```

**戻り値構造**:

place_ticket (14要素):
```
[0]  ticket_flag     # チケットID（正の整数）
[1]  reward_benefit  # 報酬（利益）
[2]  reward_other    # その他報酬
[3]  reward_other    # その他報酬
[4]  penalty_code    # ペナルティ/理由コード
[5]  current_rate    # 現在価格
[6-13] actions_echo  # アクションエコー
```

place_token (18要素):
```
[0]  token_flag      # トークンID（負の整数）
[1]  reward_benefit  # 報酬（利益）
[2]  reward_other    # その他報酬
[3]  reward_other    # その他報酬
[4]  penalty_code    # ペナルティ/理由コード
[5]  current_rate    # 現在価格
[6-17] actions_echo  # アクションエコー
```

### 3.4 close_step() パラメータ

```python
close_step(
    flags: List[int],    # 決済対象の Ticket ID
    actions: List[int],  # アクション (1=全決済, 2=部分決済)
    ratios: List[float], # 決済比率 (0.0-1.0, action=2 の場合のみ)
    timeout_secs: float = 10.0
) -> ndarray[N, 5]
```

**アクションコード**:
| 値 | 名前 | 説明 |
|----|------|------|
| 1 | ACTION_CLOSE | 全決済 |
| 2 | ACTION_REDUCE | 部分決済（ratios で比率指定） |

---

## 4. バイナリエンコーディング

### 4.1 VecF64（1次元配列）

```
┌──────────┬──────────────────────────────┐
│ count    │ values                        │
│ (u32)    │ (f64 × count)                │
└──────────┴──────────────────────────────┘
4 bytes    8 × count bytes
```

### 4.2 MatF64（2次元行列）

```
┌──────────┬──────────┬────────────────────┐
│ rows     │ cols     │ values             │
│ (u32)    │ (u32)    │ (f64 × rows×cols) │
└──────────┴──────────┴────────────────────┘
4 bytes    4 bytes    8 × rows × cols bytes
```

### 4.3 CloseStep（決済リクエスト）

```
┌──────────┬──────────────┬──────────────┬───────────────┐
│ n        │ flags        │ actions      │ ratios        │
│ (u32)    │ (i32 × n)    │ (i32 × n)    │ (f64 × n)     │
└──────────┴──────────────┴──────────────┴───────────────┘
4 bytes    4 × n bytes    4 × n bytes    8 × n bytes
```

### 4.4 エラーレスポンス

```
┌──────────┬──────────┬──────────────┬─────────────────┐
│ err_code │ sub_code │ msg_len      │ message         │
│ (u16)    │ (u16)    │ (u32)        │ (UTF-8 bytes)   │
└──────────┴──────────┴──────────────┴─────────────────┘
2 bytes    2 bytes    4 bytes        msg_len bytes
```

---

## 5. 実行フロー

### 5.1 シミュレーション実行シーケンス

```
Python                          WASM (Browser)
  │                                  │
  │  1. start()                      │
  │  ───────────────────────────►    │
  │      WebSocket Server 起動        │
  │                                  │
  │  2. wait_connected()             │
  │  ◄───────────────────────────    │
  │      Browser が接続               │
  │                                  │
  │  3. Handshake JSON               │
  │  ───────────────────────────►    │
  │      {"type":"handshake",...}    │
  │                                  │
  │  4. init_ohlc5(ohlc)             │
  │  ───────────────────────────►    │
  │      FN_INIT + MatF64            │
  │  ◄───────────────────────────    │
  │      MSG_RESULT                   │
  │                                  │
  │  ┌─── Simulation Loop ───┐       │
  │  │                       │       │
  │  │ 5. strategy.step(ctx) │       │
  │  │    - place_ticket()   │       │
  │  │    - close_step()     │       │
  │  │                       │       │
  │  │ 6. step_next()        │       │
  │  │ ──────────────────►   │       │
  │  │ ◄──────────────────   │       │
  │  │                       │       │
  │  │ 7. affect() / refresh │       │
  │  │ ──────────────────►   │       │
  │  │ ◄──────────────────   │       │
  │  │                       │       │
  │  └───────────────────────┘       │
  │                                  │
  │  8. game_end()                   │
  │  ───────────────────────────►    │
  │  ◄───────────────────────────    │
  │      最終結果                     │
  │                                  │
```

### 5.2 Gate Policy

**eager モード**:
- 各エンジン呼び出し後に即座にステートを同期
- 高精度だが低速
- デフォルト（安全側）

**step_end モード**:
- ステップ内ではキャッシュを使用
- step_next() 後に同期
- 高速だが途中状態は古い可能性

---

## 6. エラーハンドリング

### 6.1 エラー種別

| 種別 | 説明 | 対処 |
|------|------|------|
| RpcTransportError | 通信エラー（タイムアウト含む） | リトライまたは終了 |
| RpcError | WASM 側エラー（無効パラメータ等） | パラメータ確認 |
| ConnectionError | 接続断 | 再接続または終了 |

### 6.2 タイムアウト

- デフォルト: 10.0 秒
- 全 RPC メソッドで個別設定可能
- タイムアウト時は RustError 例外

---

## 7. 使用例

### 7.1 基本的な戦略

```python
from py_engine.strategy.api import Strategy, Context

class SimpleStrategy(Strategy):
    """移動平均クロスオーバー戦略"""

    async def step(self, ctx: Context) -> None:
        statics = ctx.state.statics

        # 初回のみ初期化
        if 'prices' not in ctx.user:
            ctx.user['prices'] = []
            ctx.user['position'] = None

        # 価格履歴を記録
        ctx.user['prices'].append(statics.current_rate)
        prices = ctx.user['prices']

        # 20期間必要
        if len(prices) < 20:
            return

        # 移動平均計算
        ma_short = sum(prices[-5:]) / 5
        ma_long = sum(prices[-20:]) / 20

        # エントリー
        if ctx.user['position'] is None:
            if ma_short > ma_long:
                result = await ctx.engine.place_ticket(
                    side="buy",
                    units=100,
                    stop_order_pips=50
                )
                ctx.user['position'] = int(result[0])

        # エグジット
        elif ma_short < ma_long:
            await ctx.engine.close_step(
                flags=[ctx.user['position']],
                actions=[1],
                ratios=[0.0]
            )
            ctx.user['position'] = None
```

### 7.2 実行スクリプト

```python
import asyncio
from py_engine.runtime.rust_engine_async_adapter import RustEngineAsyncAdapter
from py_engine.runtime.loop import run_attached
from my_strategy import SimpleStrategy

async def main():
    # エンジン作成
    engine = RustEngineAsyncAdapter(
        host="127.0.0.1",
        port=8787
    )

    # サーバー起動
    await engine.start()
    print("Waiting for browser connection...")

    # ブラウザ接続待ち
    await engine.wait_connected(timeout=60.0)
    print("Connected!")

    # 戦略実行
    strategy = SimpleStrategy()
    result = await run_attached(
        engine,
        strategy,
        gate_policy="eager"
    )

    # 結果表示
    print(f"Total steps: {result.steps}")
    print(f"Final assets: {result.final_assets()}")
    print(f"Max drawdown: {result.max_drawdown()}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 8. 制限事項

1. **単一接続**: WebSocket 接続は 1 本のみ
2. **同期 RPC**: 並列 RPC 呼び出し不可（ロックステップ）
3. **バックテスト専用**: リアルタイムトレーディング非対応
4. **OHLC 固定**: シミュレーション中のデータ変更不可

---

## 9. 将来の拡張予定

- [ ] 複数通貨ペア対応
- [ ] 並列 RPC サポート
- [ ] ライブトレーディングアダプター
- [ ] 戦略パラメータ最適化フレームワーク
