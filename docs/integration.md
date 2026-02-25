# UI・WASM・py_engine 統合フロー仕様書

## 1. 概要

本書では、トレーディングシミュレータにおける UI（ブラウザ）、WASM（シミュレータエンジン）、py_engine（Python戦略実行環境）の3コンポーネント間の連携フローを定義する。

### 1.1 コンポーネント構成

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (UI)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ データ選択    │  │ パラメータ設定 │  │ 結果表示・保存       │   │
│  │ FormView     │  │ Settings     │  │ simulation_results   │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│         ▼                 ▼                      ▲               │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                 WASM Simulator                               │ │
│  │  - MarketSimulator (市場シミュレーション)                     │ │
│  │  - TicketManager (ポジション管理)                             │ │
│  │  - WebSocket Client (py_engine との通信)                      │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
└─────────────────────────────┼────────────────────────────────────┘
                              │ WebSocket (Binary RPC)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      py_engine (Python)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Rust Core    │  │ BoundEngine  │  │ Strategy             │   │
│  │ (WS Server)  │  │ (Gate管理)   │  │ (ユーザー実装)         │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 通信プロトコル

| 項目 | 仕様 |
|------|------|
| トランスポート | WebSocket over TCP |
| データ形式 | Binary（16バイトヘッダー + ペイロード） |
| 通信パターン | Request-Response（ロックステップRPC） |
| 方向 | py_engine → WASM（リクエスト）、WASM → py_engine（レスポンス） |

---

## 2. データ選択フェーズ

### 2.1 UI側処理フロー

```
User Action                    UI (Browser)                        Backend (Django)
    │                              │                                    │
    │  1. データセット選択           │                                    │
    │  ──────────────────────────► │                                    │
    │                              │  2. OHLCデータ取得リクエスト          │
    │                              │  ─────────────────────────────────► │
    │                              │                                    │
    │                              │  3. OHLCデータ返却 (JSON)           │
    │                              │  ◄───────────────────────────────── │
    │                              │                                    │
    │  4. データプレビュー表示       │                                    │
    │  ◄────────────────────────── │                                    │
```

### 2.2 OHLC データ形式

| フィールド | 型 | 説明 |
|-----------|-----|------|
| time | int | タイムスタンプ（ミリ秒） |
| open | float | 始値 |
| close | float | 終値 |
| high | float | 高値 |
| low | float | 安値 |

### 2.3 パラメータ設定

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|------------|------|
| leverage | int | 25 | レバレッジ倍率 |
| commission | float | 0.000 | 手数料率 |
| max_ticket_limits | int | 100 | 最大ポジション数 |
| ticket_limit_margin | float | 0.80 | 証拠金使用率上限 |
| skip_step | int | 1 | ステップスキップ数 |
| high_precision | bool | false | 高精度モード |

---

## 3. 初期化フェーズ (Init)

### 3.1 接続シーケンス

```
py_engine                       WASM                           UI
    │                              │                            │
    │  1. start()                  │                            │
    │  WebSocket Server 起動        │                            │
    │  ─────────────────────────►  │                            │
    │                              │                            │
    │                              │  2. UI から "シミュレーション開始"  │
    │                              │  ◄─────────────────────────────── │
    │                              │                            │
    │  3. WebSocket 接続            │                            │
    │  ◄──────────────────────────  │                            │
    │                              │                            │
    │  4. Handshake (JSON)         │                            │
    │  ─────────────────────────►  │                            │
    │  {"type":"handshake",        │                            │
    │   "python_library_version":  │                            │
    │   "0.1.0"}                   │                            │
    │                              │                            │
    │  5. wait_connected() 完了    │                            │
    │                              │                            │
```

### 3.2 OHLC 初期化シーケンス

```
py_engine                       WASM
    │                              │
    │  init_ohlc5(ohlc_data)       │
    │  ─────────────────────────►  │
    │  [FN_INIT: 100]              │
    │  Header(16) + MatF64(N×5)    │
    │                              │
    │                              │ ┌─────────────────────────┐
    │                              │ │ WASM 内部処理:           │
    │                              │ │ - データバッファ確保      │
    │                              │ │ - 初期ステート設定        │
    │                              │ │ - 統計情報初期化         │
    │                              │ └─────────────────────────┘
    │                              │
    │  MSG_RESULT                  │
    │  ◄──────────────────────────  │
    │  [seq, fn_id, empty payload] │
    │                              │
```

### 3.3 FN_INIT ペイロード形式

```
┌──────────┬──────────┬────────────────────────────────┐
│ rows     │ cols     │ values                          │
│ (u32)    │ (u32)    │ (f64 × rows × cols)            │
│ = N      │ = 5      │ time,open,close,high,low × N   │
└──────────┴──────────┴────────────────────────────────┘
  4 bytes    4 bytes    8 × N × 5 bytes
```

---

## 4. シミュレーション実行フェーズ

### 4.1 メインループシーケンス

```
py_engine                       WASM                           UI
    │                              │                            │
    │  ┌─── Simulation Loop ─────────────────────────────────┐  │
    │  │                          │                          │  │
    │  │ 1. step_next()           │                          │  │
    │  │ ─────────────────────►   │                          │  │
    │  │ [FN_STEP_NEXT: 2]        │                          │  │
    │  │                          │                          │  │
    │  │                          │ 時刻更新・価格変動         │  │
    │  │                          │                          │  │
    │  │ MSG_RESULT               │                          │  │
    │  │ ◄─────────────────────   │                          │  │
    │  │                          │                          │  │
    │  │ 2. affect()              │                          │  │
    │  │ ─────────────────────►   │                          │  │
    │  │ [FN_AFFECT: 30]          │                          │  │
    │  │                          │                          │  │
    │  │                          │ イベント処理:              │  │
    │  │                          │ - Token約定判定           │  │
    │  │                          │ - TP/SL判定              │  │
    │  │                          │ - トレール更新            │  │
    │  │                          │                          │  │
    │  │ MSG_RESULT (events)      │                          │  │
    │  │ ◄─────────────────────   │                          │  │
    │  │ MatF64[N+1, 5]           │                          │  │
    │  │                          │                          │  │
    │  │ 3. get_statics()         │                          │  │
    │  │ ─────────────────────►   │                          │  │
    │  │ [FN_GET_STATICS: 12]     │                          │  │
    │  │                          │                          │  │
    │  │ MSG_RESULT (statics)     │                          │  │
    │  │ ◄─────────────────────   │                          │  │
    │  │ VecF64[20]               │                          │  │
    │  │                          │                          │  │
    │  │ 4. Strategy.step(ctx)    │                          │  │
    │  │    ユーザー戦略実行        │                          │  │
    │  │    - 注文判断             │                          │  │
    │  │    - place_ticket()      │                          │  │
    │  │    - place_token()       │                          │  │
    │  │    - close_step()        │                          │  │
    │  │                          │                          │  │
    │  │                          │                          │  │
    │  │ 5. stat_history 記録     │                          │  │
    │  │                          │  ──────────────────────► │  │
    │  │                          │  localStorage 保存        │  │
    │  │                          │                          │  │
    │  └──────────────────────────┴──────────────────────────┘  │
```

### 4.2 複合ステップ操作 (最適化版)

効率的な実行のため、`step_next_affect_statics()` を使用:

```
py_engine                       WASM
    │                              │
    │  step_next_affect_statics()  │
    │  ────────────────────────►   │
    │  [FN_STEP_NEXT_AFFECT_       │
    │   STATICS: 130]              │
    │                              │
    │                              │ ┌────────────────────┐
    │                              │ │ 1. step_next       │
    │                              │ │ 2. affect          │
    │                              │ │ 3. get_statics     │
    │                              │ └────────────────────┘
    │                              │
    │  MSG_RESULT                  │
    │  ◄────────────────────────   │
    │  [events: MatF64,            │
    │   statics: VecF64]           │
```

### 4.3 注文処理フロー

#### 4.3.1 成行注文 (place_ticket)

```
py_engine                       WASM
    │                              │
    │  place_ticket(              │
    │    side="buy",              │
    │    units=100,               │
    │    stop_order_pips=50       │
    │  )                          │
    │  ────────────────────────►   │
    │  [FN_STEP_MAKE_TICKET: 21]   │
    │                              │
    │                              │ ┌────────────────────┐
    │                              │ │ 1. 証拠金チェック   │
    │                              │ │ 2. Ticket作成      │
    │                              │ │ 3. 即時約定        │
    │                              │ └────────────────────┘
    │                              │
    │  MSG_RESULT                  │
    │  ◄────────────────────────   │
    │  VecF64[14]                  │
    │  [ticket_flag, ...]          │
```

#### 4.3.2 予約注文 (place_token)

```
py_engine                       WASM
    │                              │
    │  place_token(               │
    │    side="buy",              │
    │    order="limit",           │
    │    price=145.50,            │
    │    units=100                │
    │  )                          │
    │  ────────────────────────►   │
    │  [FN_STEP_MAKE_TOKEN: 20]    │
    │                              │
    │                              │ ┌────────────────────┐
    │                              │ │ 1. Token作成       │
    │                              │ │ 2. 待機キューに追加 │
    │                              │ └────────────────────┘
    │                              │
    │  MSG_RESULT                  │
    │  ◄────────────────────────   │
    │  VecF64[18]                  │
    │  [token_flag, ...]           │
```

#### 4.3.3 決済処理 (close_step)

```
py_engine                       WASM
    │                              │
    │  close_step(                │
    │    flags=[1, 2],            │
    │    actions=[1, 2],          │
    │    ratios=[0.0, 0.5]        │
    │  )                          │
    │  ────────────────────────►   │
    │  [FN_CLOSE_STEP: 31]         │
    │                              │
    │                              │ ┌────────────────────┐
    │                              │ │ 1. Ticket検索      │
    │                              │ │ 2. 全決済/部分決済  │
    │                              │ │ 3. 損益計算        │
    │                              │ └────────────────────┘
    │                              │
    │  MSG_RESULT                  │
    │  ◄────────────────────────   │
    │  MatF64[N, 5]                │
    │  [ticket_flag, pnl, ...]     │
```

---

## 5. 終了判定フェーズ

### 5.1 終了条件

| 終了タイプ | 条件 | 終了コード |
|-----------|------|-----------|
| GAME_END | current_step ≥ total_steps - 1 | 1 (正常終了) |
| GAME_BREAK | margin_ratio > 1.0 (証拠金不足) | -1 (強制終了) |

### 5.2 正常終了 (GAME_END)

```
py_engine                       WASM                           UI
    │                              │                            │
    │  (current_step == total_steps - 1 を検知)                  │
    │                              │                            │
    │  game_end()                  │                            │
    │  ────────────────────────►   │                            │
    │  [FN_GAME_END: 40]           │                            │
    │                              │                            │
    │                              │ ┌────────────────────┐     │
    │                              │ │ 全ポジション強制決済 │     │
    │                              │ │ 最終統計計算        │     │
    │                              │ └────────────────────┘     │
    │                              │                            │
    │  MSG_RESULT                  │                            │
    │  ◄────────────────────────   │                            │
    │  MatF64[N+1, 5]              │                            │
    │  サマリー行: [1,1,1,1,1]      │                            │
    │                              │                            │
    │                              │  終了イベント通知          │
    │                              │  ────────────────────────► │
```

### 5.3 強制終了 (GAME_BREAK)

```
py_engine                       WASM                           UI
    │                              │                            │
    │  affect() 呼び出し           │                            │
    │  ────────────────────────►   │                            │
    │                              │                            │
    │                              │ ┌────────────────────┐     │
    │                              │ │ margin_ratio > 1.0  │     │
    │                              │ │ → 強制終了判定      │     │
    │                              │ │ 全ポジション清算    │     │
    │                              │ └────────────────────┘     │
    │                              │                            │
    │  MSG_RESULT                  │                            │
    │  ◄────────────────────────   │                            │
    │  MatF64[N+1, 5]              │                            │
    │  サマリー行: [1,-1,1,1,1]     │                            │
    │  (pnl_ratio=-1 で強制終了)    │                            │
    │                              │                            │
    │  done=True, done_code=-1     │                            │
    │  を検知してループ終了         │                            │
```

### 5.4 終了判定ロジック (py_engine側)

```python
# affect() の戻り値を解析
events = await engine.affect()
last_row = events[-1]  # サマリー行

if last_row[0] >= 1:  # ticket_flag >= 1
    if last_row[1] == -1:  # pnl_ratio == -1
        # GAME_BREAK (強制終了)
        done = True
        done_code = -1
    elif last_row[1] == 1 and all(last_row[2:] == 1):
        # GAME_END (正常終了)
        done = True
        done_code = 1
```

---

## 6. 結果生成フェーズ

### 6.1 データ収集

シミュレーション中に以下のデータを収集:

| データ項目 | 収集タイミング | 保存先 |
|-----------|--------------|--------|
| stat_history | 各ステップ終了時 | localStorage |
| ticket_traces | 決済時 | localStorage |
| order_history | 注文発行時 | localStorage |

### 6.2 stat_history 構造

```javascript
{
  "currentTime": 1705571200000,    // タイムスタンプ (ms)
  "assets": 10203.48,              // 口座残高
  "virtualAssets": 10257.04,       // 評価額
  "requiredMargin": 1234.56,       // 必要証拠金
  "marginRatio": 0.12,             // 証拠金使用率
  "currentRate": 145.123,          // 現在価格
  "ticketsNum": 3,                 // オープンポジション数
  "benefitBuy": 53.64,             // BUY含み損益
  "benefitSell": -12.30            // SELL含み損益
}
```

### 6.3 結果生成シーケンス

```
py_engine                       WASM                           UI
    │                              │                            │
    │  (シミュレーション終了)        │                            │
    │                              │                            │
    │  get_statics() (最終統計)    │                            │
    │  ────────────────────────►   │                            │
    │  ◄────────────────────────   │                            │
    │                              │                            │
    │                              │  stat_history 完了         │
    │                              │  ────────────────────────► │
    │                              │                            │
    │                              │                            │  ┌────────────────────┐
    │                              │                            │  │ 統計計算:           │
    │                              │                            │  │ - total_return     │
    │                              │                            │  │ - max_drawdown     │
    │                              │                            │  │ - win_rate         │
    │                              │                            │  │ - profit_factor    │
    │                              │                            │  └────────────────────┘
    │                              │                            │
    │                              │                            │  summary.json 生成
    │                              │                            │  ↓
    │                              │                            │  Django API 保存
```

### 6.4 summary.json 構造

```json
{
  "meta": {
    "id": "uuid",
    "title": null,
    "memo": null,
    "created_at": "2026-01-18T03:43:31.923297+00:00",
    "ohlc_dataset": {
      "log_cd": 99,
      "name": "データセット名"
    }
  },
  "environment": {
    "strategy_name": null,
    "simulator_engine_version": "1.0",
    "python_library_version": "0.1.0"
  },
  "settings": {
    "data_start": 1705571200000,
    "data_end": 1705657600000,
    "skip_step": "1",
    "leverage": "25",
    "commission": "0.000",
    "max_ticket_limits": "100",
    "ticket_limit_margin": "0.80",
    "log_skip_step": "1",
    "high_precision": false
  },
  "computed_stats": {
    "total_return": 2.03,
    "max_drawdown": -5.54,
    "win_rate": 48.65,
    "profit_factor": 1.01,
    "total_orders": 668,
    "closed_orders": 668
  },
  "performance": {
    "initial_assets": 10000,
    "final_balance": 10203.48,
    "final_equity": 10257.04
  }
}
```

---

## 7. 状態遷移図

### 7.1 WASM シミュレータ状態

```
                    ┌─────────────┐
                    │   IDLE      │
                    └──────┬──────┘
                           │ FN_INIT
                           ▼
                    ┌─────────────┐
                    │ INITIALIZED │
                    └──────┬──────┘
                           │ FN_STEP_NEXT
                           ▼
        ┌──────────────────────────────────┐
        │                                  │
        │         ┌─────────────┐          │
        │    ┌───►│  STEPPING   │◄───┐     │
        │    │    └──────┬──────┘    │     │
        │    │           │           │     │
        │    │ FN_STEP   │ FN_AFFECT │     │
        │    │ _NEXT     │           │     │
        │    │           ▼           │     │
        │    │    ┌─────────────┐    │     │
        │    └────│  AFFECTING  │────┘     │
        │         └──────┬──────┘          │
        │                │                 │
        │    margin_ratio│>1.0             │ current_step
        │                │                 │ >= total_steps
        │                ▼                 │
        │         ┌─────────────┐          │
        │         │ GAME_BREAK  │          │
        │         └─────────────┘          │
        │                                  │
        └──────────────────────────────────┘
                           │ FN_GAME_END
                           ▼
                    ┌─────────────┐
                    │  GAME_END   │
                    └─────────────┘
```

### 7.2 py_engine 実行状態

```
      ┌──────────────┐
      │    INIT      │
      └───────┬──────┘
              │ start()
              ▼
      ┌──────────────┐
      │   WAITING    │ ◄── wait_connected()
      └───────┬──────┘
              │ 接続完了
              ▼
      ┌──────────────┐
      │  CONNECTED   │ ◄── init_ohlc5()
      └───────┬──────┘
              │ 初期化完了
              ▼
      ┌──────────────┐
      │   RUNNING    │ ◄── step_next / affect / strategy.step
      └───────┬──────┘
              │ done=True
              ▼
      ┌──────────────┐
      │   FINISHED   │ ◄── game_end()
      └──────────────┘
```

---

## 8. エラーハンドリング

### 8.1 通信エラー

| エラー種別 | 原因 | 対処 |
|-----------|------|------|
| ConnectionError | WebSocket 切断 | 再接続または終了 |
| TimeoutError | レスポンス待ちタイムアウト | リトライまたは終了 |
| ProtocolError | プロトコルバージョン不一致 | バージョン確認 |

### 8.2 ビジネスエラー

| エラーコード | 意味 | 対処 |
|------------|------|------|
| -1 (ticket_flag) | 証拠金不足 | 注文サイズ縮小 |
| -2 (ticket_flag) | ポジション上限超過 | 既存ポジション決済 |

### 8.3 エラーレスポンス形式

```
┌──────────┬──────────┬──────────────┬─────────────────┐
│ err_code │ sub_code │ msg_len      │ message         │
│ (u16)    │ (u16)    │ (u32)        │ (UTF-8 bytes)   │
└──────────┴──────────┴──────────────┴─────────────────┘
```

---

## 9. 付録

### 9.1 ファンクションID一覧

| ID | 名前 | 方向 | 説明 |
|----|------|------|------|
| 100 | FN_INIT | Py→WASM | OHLC データ初期化 |
| 2 | FN_STEP_NEXT | Py→WASM | ステップ進行 |
| 130 | FN_STEP_NEXT_AFFECT_STATICS | Py→WASM | 複合操作 |
| 12 | FN_GET_STATICS | Py→WASM | 統計情報取得 |
| 10 | FN_GET_TICKET_LIST | Py→WASM | ポジション一覧 |
| 30 | FN_AFFECT | Py→WASM | イベント実行 |
| 40 | FN_GAME_END | Py→WASM | シミュレーション終了 |
| 31 | FN_CLOSE_STEP | Py→WASM | ポジション決済 |
| 20 | FN_STEP_MAKE_TOKEN | Py→WASM | 予約注文作成 |
| 21 | FN_STEP_MAKE_TICKET | Py→WASM | 成行注文作成 |
| 120 | FN_GET_GATE_POLICY | Py→WASM | 同期ポリシー取得 |

### 9.2 メッセージタイプ一覧

| 値 | 名前 | 方向 | 説明 |
|----|------|------|------|
| 1 | MSG_RUN | Py→WASM | コマンド送信 |
| 2 | MSG_RESULT | WASM→Py | 成功レスポンス |
| 3 | MSG_ERROR | WASM→Py | エラーレスポンス |
| 4 | MSG_PING | WASM→Py | Keep-alive |
| 5 | MSG_PONG | Py→WASM | Ping 応答 |

### 9.3 関連ドキュメント

- [要件定義書](./requirements.md) - py_engine API 仕様
- [詳細設計書](./design.md) - py_engine 内部設計
