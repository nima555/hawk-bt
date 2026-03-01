# py_engine 要件定義書

## 1. 概要

### 1.1 目的
py_engineは、トレーディングシミュレータ（WASM）と連携し、Pythonで戦略を記述・実行するためのクライアントライブラリである。

### 1.2 システム構成
```
┌─────────────────────────────┐
│  ユーザー戦略 (Python)       │
│  Strategy.step()            │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  py_engine (Rust + PyO3)    │
│  - WebSocket Server         │
│  - Binary RPC Protocol      │
└──────────┬──────────────────┘
           │ WebSocket (Binary)
           ▼
┌─────────────────────────────┐
│  WASM Simulator (Browser)   │
│  - マーケットシミュレーション   │
│  - 注文執行・ポジション管理    │
└─────────────────────────────┘
```

### 1.3 バージョン
- ライブラリバージョン: 0.1.0
- プロトコルバージョン: 1

---

## 2. 機能要件

### 2.1 接続・初期化機能

#### F-001: エンジン初期化
| 項目 | 内容 |
|------|------|
| 関数名 | `RustEngineAsync(host, port, start_seq)` |
| 説明 | エンジンインスタンスを作成 |
| 入力 | `host: str` - バインドアドレス (デフォルト: "127.0.0.1")<br>`port: int` - ポート番号 (デフォルト: 8787)<br>`start_seq: int` - 初期シーケンス番号 (デフォルト: 1) |
| 戻り値 | `RustEngineAsync` - エンジンインスタンス |

#### F-002: サーバー起動
| 項目 | 内容 |
|------|------|
| 関数名 | `async start()` |
| 説明 | WebSocketサーバーを起動（ノンブロッキング） |
| 入力 | なし |
| 戻り値 | `None` |

#### F-003: 接続待機
| 項目 | 内容 |
|------|------|
| 関数名 | `async wait_connected(timeout_secs)` |
| 説明 | ブラウザ（WASM）からの接続を待機 |
| 入力 | `timeout_secs: float` - タイムアウト秒数 (None=無制限) |
| 戻り値 | `None` |
| 例外 | `TimeoutError` - タイムアウト時 |

#### F-004: OHLC データ初期化
| 項目 | 内容 |
|------|------|
| 関数名 | `async init_ohlc5(ohlc5, timeout_secs)` |
| 説明 | シミュレータをOHLCデータで初期化 |
| 入力 | `ohlc5: ndarray[N, 5]` - OHLC行列 (time, open, close, high, low)<br>`timeout_secs: float` - タイムアウト (デフォルト: 10.0) |
| 戻り値 | `None` |

---

### 2.2 注文機能

#### F-010: 成行注文（Ticket）
| 項目 | 内容 |
|------|------|
| 関数名 | `async place_ticket(side, units, sub_limit_pips, stop_order_pips, trail_pips, timeout_secs)` |
| 説明 | 成行注文を発行し即時約定 |
| 入力 | `side: str` - "buy" または "sell"<br>`units: int` - ポジションサイズ (> 0)<br>`sub_limit_pips: float` - 利確幅 (pips, 省略可)<br>`stop_order_pips: float` - 損切幅 (pips, 省略可)<br>`trail_pips: float` - トレール幅 (pips, 省略可)<br>`timeout_secs: float` - タイムアウト (デフォルト: 10.0) |

**戻り値**: `ndarray[14]` - 注文結果

| Index | フィールド名 | 型 | 説明 | 値の範囲 |
|-------|-------------|-----|------|----------|
| 0 | ticket_flag | int | チケットID | ≥1: 成功, -1: 証拠金不足, -2: 上限超過 |
| 1 | reward_1 | float | 報酬1（成功時0） | 0 |
| 2 | reward_2 | float | 報酬2（成功時0） | 0 |
| 3 | trading_format | float | 売買方向 | 1.0=BUY, 0.0=SELL |
| 4 | status_flag | float | ステータス | -1: 正常 |
| 5 | current_rate | float | 約定価格 | 市場価格 |
| 6-13 | action_echo | float | 入力パラメータのエコー | 入力値 |

#### F-011: 予約注文（Token）
| 項目 | 内容 |
|------|------|
| 関数名 | `async place_token(side, order, price, units, sub_limit_pips, stop_order_pips, trail_pips, time_limits, timeout_secs)` |
| 説明 | 指値/逆指値注文を発行 |
| 入力 | `side: str` - "buy" または "sell"<br>`order: str` - "limit" または "stop"<br>`price: float` - 発注価格<br>`units: int` - ポジションサイズ (> 0)<br>`sub_limit_pips: float` - 利確幅 (pips, 省略可)<br>`stop_order_pips: float` - 損切幅 (pips, 省略可)<br>`trail_pips: float` - トレール幅 (pips, 省略可)<br>`time_limits: float` - 有効時間 (省略可)<br>`timeout_secs: float` - タイムアウト (デフォルト: 10.0) |

**戻り値**: `ndarray[18]` - 注文結果

| Index | フィールド名 | 型 | 説明 | 値の範囲 |
|-------|-------------|-----|------|----------|
| 0 | token_flag | int | トークンID | ≥1: 成功 |
| 1 | reward_1 | float | 報酬1 | 0 |
| 2 | reward_2 | float | 報酬2 | 0 |
| 3 | token_format | float | 売買方向 | 1.0=BUY, 0.0=SELL |
| 4 | status_flag | float | ステータス | -1: 正常 |
| 5 | current_rate | float | 現在価格 | 市場価格 |
| 6-17 | action_echo | float | 入力パラメータのエコー | 入力値 |

#### F-012: ポジション決済
| 項目 | 内容 |
|------|------|
| 関数名 | `async close_step(flags, actions, ratios, timeout_secs)` |
| 説明 | 指定ポジションを決済（全決済または部分決済） |
| 入力 | `flags: List[int]` - 決済対象のticket_flag一覧<br>`actions: List[int]` - アクション (1=全決済, 2=部分決済)<br>`ratios: List[float]` - 決済比率 (0.0-1.0, action=2の場合のみ使用)<br>`timeout_secs: float` - タイムアウト (デフォルト: 10.0) |

**戻り値**: `ndarray[N, 5]` - 決済イベント行列（N=決済対象数）

| Column | フィールド名 | 型 | 説明 | 値の範囲 |
|--------|-------------|-----|------|----------|
| 0 | ticket_flag | int | チケットID | 入力のflag値 |
| 1 | realized_pnl | float | 実現損益 | 任意の値 |
| 2 | differential_reward | float | 差分報酬 | 任意の値 |
| 3 | trading_format | float | 売買方向 | 1.0=BUY, 0.0=SELL |
| 4 | action_result | int | 結果 | 3=成功, -1=未発見 |

---

### 2.3 データ取得機能

#### F-020: 統計情報取得
| 項目 | 内容 |
|------|------|
| 関数名 | `async get_statics(timeout_secs)` |
| 説明 | 現在のシミュレータ状態を取得 |
| 入力 | `timeout_secs: float` - タイムアウト (デフォルト: 10.0) |

**戻り値**: `ndarray[20]` - 統計情報

| Index | フィールド名 | 型 | 説明 | 値の範囲 |
|-------|-------------|-----|------|----------|
| 0 | assets | float | 口座残高（確定） | > 0 |
| 1 | virtual_assets | float | 評価額（含み損益込み） | > 0 |
| 2 | required_margin | float | 必要証拠金 | ≥ 0 |
| 3 | margin_ratio | float | 証拠金使用率 (required_margin / virtual_assets) | 0.0〜∞ (>1.0で強制決済) |
| 4 | current_rate | float | 現在価格（終値） | 市場価格 |
| 5 | current_time_ms | float | 現在時刻（ミリ秒） | タイムスタンプ |
| 6 | current_step | int | 現在ステップ番号 | 0 〜 N-1 |
| 7 | token_num | int | アクティブToken数 | 0 〜 token_limits |
| 8 | tickets_num | int | オープンTicket数 | 0 〜 ticket_limits |
| 9 | ticket_all_num | int | 累計Ticket数 | ≥ 0 |
| 10 | count | int | ステップカウンタ | 0 〜 total_steps |
| 11 | benefit_long | float | ロングポジション含み損益 | 任意の値 |
| 12 | benefit_short | float | ショートポジション含み損益 | 任意の値 |
| 13 | unit_long | float | ロングポジション総数量 | ≥ 0 |
| 14 | unit_short | float | ショートポジション総数量 | ≥ 0 |
| 15 | ticket_long_count | int | ロングチケット数 | 0 〜 tickets_num |
| 16 | ticket_short_count | int | ショートチケット数 | 0 〜 tickets_num |
| 17 | token_long_count | int | ロングトークン数 | 0 〜 token_num |
| 18 | token_short_count | int | ショートトークン数 | 0 〜 token_num |
| 19 | total_steps | int | 総ステップ数 | N（データ行数） |

#### F-021: ポジション一覧取得
| 項目 | 内容 |
|------|------|
| 関数名 | `async get_ticket_list(timeout_secs)` |
| 説明 | オープンポジションの一覧を取得 |
| 入力 | `timeout_secs: float` - タイムアウト (デフォルト: 10.0) |

**戻り値**: `ndarray[N, 10]` - ポジション行列（N=オープンポジション数）

| Column | フィールド名 | 型 | 説明 | 値の範囲 |
|--------|-------------|-----|------|----------|
| 0 | ticket_flag | int | チケットID | ≥ 1 |
| 1 | tp_flag | float | 利確設定有無 | 1.0=有, 0.0=無 |
| 2 | sl_flag | float | 損切設定有無 | 1.0=有, 0.0=無 |
| 3 | trail_flag | float | トレール設定有無 | 1.0=有, 0.0=無 |
| 4 | trading_format | float | 売買方向 | 1.0=BUY, 0.0=SELL |
| 5 | units | float | ポジションサイズ | > 0 |
| 6 | tp_pips | float | 利確幅（pips） | col[1]=1の時 > 0 |
| 7 | sl_pips | float | 損切幅（pips） | col[2]=1の時 > 0 |
| 8 | trail_pips | float | トレール幅（pips） | col[3]=1の時 > 0 |
| 9 | pnl | float | 現在の含み損益 | units × 価格差 |

#### F-022: イベント実行・取得
| 項目 | 内容 |
|------|------|
| 関数名 | `async affect(timeout_secs)` |
| 説明 | 保留中のイベント（約定、決済等）を実行し結果を取得 |
| 入力 | `timeout_secs: float` - タイムアウト (デフォルト: 10.0) |

**戻り値**: `ndarray[N+1, 5]` - イベント行列（N=決済されたポジション数、最終行はサマリー）

| Column | フィールド名 | 型 | 説明 | 値の範囲 |
|--------|-------------|-----|------|----------|
| 0 | ticket_flag | int | チケットID（サマリー行:0または1） | ≥1（通常行）, 0/1（サマリー） |
| 1 | realized_pnl | float | 実現損益（サマリー行:-1で強制終了） | 任意の値, -1=GAME_BREAK |
| 2 | differential_reward | float | 差分報酬 | 任意の値 |
| 3 | trading_format | float | 売買方向 | 1.0=BUY, 0.0=SELL |
| 4 | close_reason | int | 決済理由 | 1=利確(TP), 0=損切(SL) |

**サマリー行（最終行）の解釈**:
- 正常: `[0, 0, 0, 0, 0]`
- 強制終了（証拠金不足）: `[1, -1, 1, 1, 1]`

---

### 2.4 シミュレーション制御

#### F-030: ステップ進行
| 項目 | 内容 |
|------|------|
| 関数名 | `async step_next(timeout_secs)` |
| 説明 | シミュレーションを1ステップ進める |
| 入力 | `timeout_secs: float` - タイムアウト (デフォルト: 10.0) |
| 戻り値 | `None` |

#### F-031: 複合ステップ（ステップ進行 + イベント + 統計取得）
| 項目 | 内容 |
|------|------|
| 関数名 | `async step_next_affect_statics(timeout_secs)` |
| 説明 | ステップ進行、イベント実行、統計取得を一括実行（高効率） |
| 入力 | `timeout_secs: float` - タイムアウト (デフォルト: 10.0) |
| 戻り値 | `Tuple[ndarray, ndarray]` - (イベント行列[N+1, 5], 統計情報[20]) |

#### F-032: シミュレーション終了
| 項目 | 内容 |
|------|------|
| 関数名 | `async game_end(timeout_secs)` |
| 説明 | シミュレーションを終了し、全ポジションを強制決済 |
| 入力 | `timeout_secs: float` - タイムアウト (デフォルト: 10.0) |

**戻り値**: `ndarray[N+1, 5]` - 最終イベント行列（N=強制決済されたポジション数）

| Column | フィールド名 | 型 | 説明 | 値の範囲 |
|--------|-------------|-----|------|----------|
| 0 | ticket_flag | int | チケットID（サマリー行:1） | ≥1（通常行）, 1（サマリー） |
| 1 | pnl_ratio | float | 損益/資産（正規化） | 任意の値, サマリー:1 |
| 2 | diff_reward_ratio | float | 差分報酬/資産 | 任意の値, サマリー:1 |
| 3 | trading_format | float | 売買方向 | 1.0=BUY, 0.0=SELL, サマリー:1 |
| 4 | close_reason | int | 決済理由 | 0/1（通常）, サマリー:1 |

**サマリー行（最終行）**: `[1, 1, 1, 1, 1]` = 正常終了

#### F-033: 同期ポリシー取得
| 項目 | 内容 |
|------|------|
| 関数名 | `async get_gate_policy_hint(timeout_secs)` |
| 説明 | ブラウザ側の推奨同期ポリシーを取得 |
| 入力 | `timeout_secs: float` - タイムアウト (デフォルト: 5.0) |
| 戻り値 | `str` - "eager" または "step_end" |

---

### 2.5 戦略インターフェース

#### F-040: 戦略クラス
| 項目 | 内容 |
|------|------|
| クラス名 | `Strategy` (抽象クラス) |
| 説明 | ユーザーが継承して戦略を実装 |

```python
class Strategy:
    async def step(self, ctx: Context) -> None:
        """各ステップで呼び出される戦略メソッド（ユーザー実装）"""
        pass
```

#### F-041: コンテキストオブジェクト
| 項目 | 内容 |
|------|------|
| クラス名 | `Context` |
| 説明 | 戦略に渡されるコンテキスト情報 |

```python
@dataclass
class Context:
    engine: Engine          # エンジンAPI（注文発行等）
    state: EngineState      # 現在のシミュレータ状態
    user: Dict[str, Any]    # ユーザー定義の永続ストレージ

@dataclass
class EngineState:
    statics: Statics        # 統計情報
    tickets: ndarray        # オープンポジション一覧
    affect_events: ndarray  # 直近のイベント
    done: bool              # 終了フラグ
    done_code: int          # 終了コード (-1=強制終了, 1=正常終了)
```

---

## 3. 非機能要件

### 3.1 パフォーマンス

| ID | 要件 | 目標値 |
|----|------|--------|
| NF-001 | RPC レイテンシ | < 10ms（ローカル接続時） |
| NF-002 | スループット | > 1000 steps/sec |
| NF-003 | メモリ使用量 | < 100MB（戦略コード除く） |

### 3.2 信頼性

| ID | 要件 | 説明 |
|----|------|------|
| NF-010 | タイムアウト | 全 RPC 呼び出しにタイムアウト設定可能 |
| NF-011 | シーケンス保証 | ロックステップ RPC でメッセージ順序保証 |
| NF-012 | エラーハンドリング | 詳細なエラーコードとメッセージ |

### 3.3 互換性

| ID | 要件 | 説明 |
|----|------|------|
| NF-020 | Python バージョン | Python 3.10 以上 |
| NF-021 | プラットフォーム | macOS (arm64), Linux (x86_64) |
| NF-022 | async/await | asyncio 完全対応 |

---

## 4. ユースケース

### 4.1 基本的なバックテスト実行

**アクター**: 開発者
**前提条件**: WASMシミュレータがブラウザで起動済み

**フロー**:
1. ユーザーが Strategy クラスを実装
2. py_engine を起動し WebSocket サーバーを開始
3. ブラウザ（WASM）が接続
4. OHLC データでシミュレータを初期化
5. 各ステップで戦略コードを実行
6. シミュレーション終了後、結果を取得

### 4.2 戦略での注文発行

**アクター**: 戦略コード
**前提条件**: シミュレーション実行中

**フロー**:
1. step() メソッドが呼び出される
2. ctx.state.statics で現在状態を確認
3. 条件に基づき place_ticket() または place_token() を呼び出し
4. 注文結果（ticket_flag）を受け取る
5. 必要に応じて ctx.user に状態を保存

### 4.3 ポジション管理

**アクター**: 戦略コード
**前提条件**: オープンポジションが存在

**フロー**:
1. get_ticket_list() でポジション一覧を取得
2. 決済条件を評価
3. close_step() で決済（全決済 or 部分決済）
4. 決済イベントを受け取る

---

## 5. 制約事項

### 5.1 技術的制約

- WebSocket 接続は 1 本のみ（複数接続非対応）
- RPC は同期的（1 リクエスト = 1 レスポンス）
- OHLC データ形式は N×5 行列（time, open, close, high, low）

### 5.2 運用上の制約

- ローカル接続（127.0.0.1）を推奨（セキュリティ）
- シミュレーション中のパラメータ変更不可
- リアルタイムトレーディングは対象外（バックテスト専用）

---

## 6. 用語定義

| 用語 | 説明 |
|------|------|
| Ticket | 成行注文で作成されたポジション |
| Token | 予約注文（指値/逆指値）、約定前の状態 |
| Statics | シミュレータの現在状態（資産、価格等） |
| Affect | イベント実行（約定、決済等の処理） |
| Gate Policy | 同期戦略（eager: 即時同期, step_end: ステップ終了時同期） |
| Pips | 価格変動の最小単位（通貨ペアにより異なる） |
