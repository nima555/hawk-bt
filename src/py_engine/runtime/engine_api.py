from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

import logging

from py_engine.runtime.rpc_client import RpcClient
from py_engine_rust import (
    decode_vec_f64_py as decode_vec_f64,
    decode_mat_f64_py as decode_mat_f64,
    decode_vec_mat_f64_py as decode_vec_mat_f64,
    encode_vec_f64_py as encode_vec_f64,
    encode_mat_f64_py as encode_mat_f64,
    encode_close_step_py as encode_close_step,
)

logger = logging.getLogger(__name__)

REWARD_GAME_BREAK = -1
REWARD_GAME_END = 1
ACTION_REDUCE = 2

# JS ws/protocol.js と一致
class FN:
    INIT = 100
    STEP_NEXT = 2
    STEP_NEXT_AFFECT_STATICS = 130
    GET_STATICS = 12
    GET_TICKET_LIST = 10
    AFFECT = 30
    GAME_END = 40
    CLOSE_STEP = 31
    STEP_MAKE_TOKEN = 20
    STEP_MAKE_TICKET = 21
    GET_GATE_POLICY = 120


@dataclass
class Statics:
    """
    WASM: get_statics() が返す VecF64 の意味（順序固定）
    """
    assets: float
    virtual_assets: float
    required_margin: float
    margin_ratio: float
    current_rate: float
    current_time_ms: float
    current_step: int  # current_sequences
    token_num: float
    tickets_num: float
    ticket_all_num: float
    count: int
    ticket_stat_0: float
    ticket_stat_1: float
    ticket_stat_2: float
    ticket_stat_3: float
    ticket_buy_count: float
    ticket_sell_count: float
    token_buy_count: float
    token_sell_count: float
    total_steps: int

    @staticmethod
    def from_vec14(v: np.ndarray) -> "Statics":
        if not isinstance(v, np.ndarray):
            raise TypeError("Statics.from_vec14 expects numpy.ndarray")
        v = np.asarray(v, dtype=np.float64)
        if v.shape[0] < 14:
            raise ValueError(f"get_statics vec must have >=14 elements, got {v.shape}")

        # 現行は 20 要素（current_time_ms を含む）を想定するが、後方互換で短い場合は0埋め
        target_size = 20
        if v.size < target_size:
            padded = np.zeros(target_size, dtype=np.float64)
            padded[: v.size] = v
            v = padded

        return Statics(
            assets=float(v[0]),
            virtual_assets=float(v[1]),
            required_margin=float(v[2]),
            margin_ratio=float(v[3]),
            current_rate=float(v[4]),
            current_time_ms=float(v[5]),
            current_step=int(v[6]),
            token_num=float(v[7]),
            tickets_num=float(v[8]),
            ticket_all_num=float(v[9]),
            count=int(v[10]),
            ticket_stat_0=float(v[11]),
            ticket_stat_1=float(v[12]),
            ticket_stat_2=float(v[13]),
            ticket_stat_3=float(v[14]),
            ticket_buy_count=float(v[15]),
            ticket_sell_count=float(v[16]),
            token_buy_count=float(v[17]),
            token_sell_count=float(v[18]),
            total_steps=int(v[19]),
        )


class EngineAPI:
    """
    WASM fnId を隠蔽する薄いラッパ（生API）。
    """

    def __init__(self, rpc: RpcClient) -> None:
        self._rpc = rpc

    async def init_ohlc5(self, ohlc5: np.ndarray, timeout: float = 10.0) -> None:
        if not isinstance(ohlc5, np.ndarray):
            raise TypeError("ohlc5 must be numpy.ndarray")
        ohlc5 = np.asarray(ohlc5, dtype=np.float64, order="C")
        if ohlc5.ndim != 2 or ohlc5.shape[1] != 5:
            raise ValueError(f"ohlc5 must be shape (N,5), got {ohlc5.shape}")

        payload = encode_mat_f64(ohlc5)
        _ = await self._rpc.send_run_and_wait(FN.INIT, payload, timeout=timeout)
        return None

    async def step_next(self, timeout: float = 10.0) -> None:
        _ = await self._rpc.send_run_and_wait(FN.STEP_NEXT, b"", timeout=timeout)
        return None

    async def step_next_affect_statics(self, timeout: float = 10.0) -> tuple[np.ndarray, Statics]:
        payload = await self._rpc.send_run_and_wait(FN.STEP_NEXT_AFFECT_STATICS, b"", timeout=timeout)
        vec, mat = decode_vec_mat_f64(payload)
        vec = np.asarray(vec)
        mat = np.asarray(mat)
        if mat.ndim != 2 or mat.shape[1] != 5:
            raise ValueError(f"STEP_NEXT_AFFECT_STATICS expected (N,5), got {mat.shape}")
        return mat, Statics.from_vec14(np.asarray(vec, dtype=np.float64))

    async def get_statics_raw(self, timeout: float = 10.0) -> np.ndarray:
        payload = await self._rpc.send_run_and_wait(FN.GET_STATICS, b"", timeout=timeout)
        vec = decode_vec_f64(payload)
        # 現行は current_time_ms を含めた 20 要素を想定。古いWASMでも落ちないように許容範囲を広げる
        if vec.size < 14:
            raise ValueError(f"GET_STATICS expected >=14 floats, got {vec.size}")
        return vec

    async def get_statics(self, timeout: float = 10.0) -> Statics:
        vec = await self.get_statics_raw(timeout=timeout)
        return Statics.from_vec14(vec)

    async def get_gate_policy_hint(self, timeout: float = 5.0) -> str | None:
        """
        ブラウザ側（UI）の高精度チェック状態を 1byte で受け取る。
        1 = eager（高精度） / 0 = step_end（高速） / それ以外は None を返す。
        """
        try:
            payload = await self._rpc.send_run_and_wait(FN.GET_GATE_POLICY, b"", timeout=timeout)
        except Exception as e:
            logger.warning("get_gate_policy_hint failed: %s", e)
            return None

        if not payload:
            return None
        try:
            flag = payload[0]
        except Exception:
            return None
        if flag == 1:
            return "eager"
        if flag == 0:
            return "step_end"
        return None

    async def get_ticket_list(self, timeout: float = 10.0) -> np.ndarray:
        """
        FN.GET_TICKET_LIST(10) -> MatF64 を np.ndarray(float64, shape=(rows, cols)) で返す
        """
        payload = await self._rpc.send_run_and_wait(FN.GET_TICKET_LIST, b"", timeout=timeout)

        decoded = decode_mat_f64(payload)
        # decode_mat_f64 の実装差異に耐える
        # - (rows, cols, ndarray) を返す場合
        # - ndarray を返す場合
        if isinstance(decoded, tuple) and len(decoded) == 3:
            rows, cols, data = decoded
            mat = np.asarray(data, dtype=np.float64).reshape((rows, cols))
            return mat

        mat = np.asarray(decoded, dtype=np.float64)
        if mat.ndim != 2:
            raise ValueError(f"GET_TICKET_LIST expected 2D matrix, got shape={mat.shape}")
        return mat
    
    async def affect(self, timeout: float = 10.0) -> np.ndarray:
        """
        FN.AFFECT(30) -> MatF64 -> np.ndarray shape=(N,5)
        columns:
          0 flag
          1 benefit
          2 (reward)  ※現状は無視してよい
          3 trading_format
          4 reason
        last row is sentinel:
          normal: [0,0,0,0,0]
          eliminated/game-break: [1, REWARD_GAME_BREAK, 1, 1, 1]  (WASM実装依存)
        """
        payload = await self._rpc.send_run_and_wait(FN.AFFECT, b"", timeout=timeout)
        mat = decode_mat_f64(payload)
        if mat.ndim != 2 or mat.shape[1] != 5:
            raise ValueError(f"AFFECT expected shape (N,5), got {mat.shape}")
        return mat
    
    async def game_end(self, timeout: float = 10.0) -> np.ndarray:
        """
        FN.GAME_END -> MatF64 (N,5)
        最後の行: benefit(col1) == REWARD_GAME_END(1)
        """
        payload = await self._rpc.send_run_and_wait(FN.GAME_END, b"", timeout=timeout)
        mat = decode_mat_f64(payload)
        if mat.ndim != 2 or mat.shape[1] != 5:
            raise ValueError(f"GAME_END expected shape (N,5), got {mat.shape}")
        return mat

    async def close_step(
        self,
        flags,
        actions,
        ratios,
        *,
        timeout: float = 10.0,
        validate: bool = True,
    ) -> np.ndarray:
        """
        WASM close_step(flags, actions, ratios) を実行し、(n,5) float64 を返す。
        flags/actions/ratios は list or np.ndarray を受け付ける（内部で np化）。
        """

        flags = np.asarray(flags, dtype=np.int32, order="C")
        actions = np.asarray(actions, dtype=np.int32, order="C")
        ratios = np.asarray(ratios, dtype=np.float64, order="C")

        if flags.shape != actions.shape or flags.shape != ratios.shape:
            raise ValueError(f"close_step shape mismatch: {flags.shape=}, {actions.shape=}, {ratios.shape=}")

        n = int(flags.size)
        if n == 0:
            return np.empty((0, 5), dtype=np.float64)

        if validate:
            # action==2 のときだけ ratio 使用（それ以外は 0 で正規化）
            # ※仕様固定したいなら必須。嫌なら正規化だけにする。
            for i, a in enumerate(actions.tolist()):
                if a == ACTION_REDUCE:
                    r = float(ratios[i])
                    if not (0.0 <= r <= 1.0):
                        raise ValueError(f"ratios[{i}] out of range for REDUCE(action=2): {r} (expected 0..1)")
                else:
                    ratios[i] = 0.0

            if np.any(flags < 0):
                raise ValueError("flags must be >= 0")
            if np.any(actions < 0):
                raise ValueError("actions must be >= 0")

        payload = encode_close_step(flags, actions, ratios)

        # ★ここは既存のRPC呼び出し関数名に合わせて1行だけ調整
        raw = await self._rpc.send_run_and_wait(FN.CLOSE_STEP, payload, timeout=timeout)

        mat = decode_mat_f64(raw)

        # 返り値チェック（WASM側が N×5 の契約）
        if mat.ndim != 2 or mat.shape[1] != 5:
            raise RuntimeError(f"close_step invalid return shape: {mat.shape}, expected (N,5)")
        if mat.shape[0] != n:
            raise RuntimeError(f"close_step invalid return rows: {mat.shape[0]}, expected {n}")
        
        not_found_mask = (mat[:, 4] == -1)

        if not_found_mask.any():
            bad_flags = flags[not_found_mask].tolist()
            logger.warning(
                "[close_step] not found ticket flag(s): %s (ignored, returned as status=-1)",
                bad_flags,
            )

        return mat
    
    
    async def place_token(
        self,
        *,
        side: str,                 # "buy" | "sell"
        order: str,                # "limit" | "stop"
        price: float,              # issue_rate (必須)
        units: int,                # 必須
        sub_limit_pips: float | None = None,
        stop_order_pips: float | None = None,
        trail_pips: float | None = None,
        time_limits: float | None = None,
        timeout: float = 10.0,
    ) -> np.ndarray:
        """
        予約注文(Token)を追加する（WASM: step_make_token を叩く）。

        戻り値: reward5state13 (shape=(18,))
        [0]=flag(トークンID), [1..4]=reward系, [5]=current_rate, [6..17]=actions写し
        """

        # --- normalize/validate ---
        side_n = str(side).strip().lower()
        order_n = str(order).strip().lower()

        if side_n not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        if order_n not in ("limit", "stop"):
            raise ValueError(f"order must be 'limit' or 'stop', got {order!r}")

        p = float(price)
        if not np.isfinite(p):
            raise ValueError(f"price must be finite, got {price!r}")

        u = int(units)
        if u <= 0:
            raise ValueError(f"units must be > 0, got {units!r}")

        def _opt_flag(v: float | None) -> float:
            return 1.0 if v is not None else -1.0

        def _pips_to_slot(pips: float) -> float:
            # C++: (actions[k] + 1) / 100.0 の逆変換
            # => actions[k] = pips*100 - 1
            x = float(pips)
            if not np.isfinite(x) or x < 0:
                raise ValueError(f"pips must be finite and >=0, got {pips!r}")
            return x * 100.0 - 1.0

        # --- build actions[0..12] (float64) ---
        actions = np.zeros(13, dtype=np.float64)

        actions[0] = 1.0  # if_make_from_action: place_token は「作る」だけなので固定
        actions[1] = p    # issue_rate (=price)

        actions[2] = _opt_flag(sub_limit_pips)
        actions[3] = _opt_flag(stop_order_pips)
        actions[4] = _opt_flag(trail_pips)
        actions[5] = _opt_flag(time_limits)

        # actions[6] -> trading_format (>=0 => 1, <0 => 0)
        # trading_format: 1=buy, 0=sell
        actions[6] = 1.0 if side_n == "buy" else -1.0

        # actions[7] -> token_format (>=0 => 1, <0 => 0)
        # token_format: 1=limit, 0=stop
        actions[7] = 1.0 if order_n == "limit" else -1.0

        actions[8] = float(u)  # C++ 側で int(actions[8]) される

        actions[9]  = _pips_to_slot(sub_limit_pips)  if sub_limit_pips  is not None else 0.0
        actions[10] = _pips_to_slot(stop_order_pips) if stop_order_pips is not None else 0.0
        actions[11] = _pips_to_slot(trail_pips)      if trail_pips      is not None else 0.0
        actions[12] = float(time_limits)             if time_limits     is not None else 0.0

        # --- call WASM directly (no dependency on step_make_token method) ---
        payload = bytes(encode_vec_f64(actions))
        raw = await self._rpc.send_run_and_wait(FN.STEP_MAKE_TOKEN, payload, timeout=timeout)
        out = decode_vec_f64(raw)

        # expected: reward5state13 => 18 elements
        if out.ndim != 1 or out.size != 18:
            raise RuntimeError(f"place_token: invalid return shape {out.shape}, expected (18,)")

        return out
    
    async def place_ticket(
        self,
        *,
        side: str,                 # "buy" | "sell"
        units: int,                # 必須
        sub_limit_pips: float | None = None,
        stop_order_pips: float | None = None,
        trail_pips: float | None = None,
        timeout: float = 10.0,
    ) -> np.ndarray:
        """
        即時チケット作成（WASM: step_make_ticket を叩く）

        ユーザー向け:
        - 必須: side, units
        - optional: sub_limit_pips / stop_order_pips / trail_pips は必要なら指定、不要なら None

        戻り値: reward5state9 (shape=(14,))
        [0]=flag, [1..4]=reward系, [5]=current_rate, [6..13]=actions写し
        """

        side_n = str(side).strip().lower()
        if side_n not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")

        u = int(units)
        if u <= 0:
            raise ValueError(f"units must be > 0, got {units!r}")

        def _if(v: float | None) -> float:
            # C++ は if_xxx == 0.0 なら nullopt、それ以外なら有効
            return 0.0 if v is None else 1.0

        def _pips_to_slot(pips: float) -> float:
            # C++: (actions[k] + 1)/100.0 の逆変換
            # => actions[k] = pips*100 - 1
            x = float(pips)
            if not np.isfinite(x) or x < 0:
                raise ValueError(f"pips must be finite and >=0, got {pips!r}")
            return x - 1.0

        # actions[0..8] を構築（C++が参照する範囲）
        actions = np.zeros(9, dtype=np.float64)

        # if_make_from_action: place_ticket は「作る」だけなので固定で 1
        actions[0] = 1.0

        actions[1] = _if(sub_limit_pips)
        actions[2] = _if(stop_order_pips)
        actions[3] = _if(trail_pips)

        # format_from_action: C++ は 1.0 なら buy、それ以外は sell として扱う前提で合わせる
        # ※ここはプロジェクト定義に合わせている（buy=1, sell=0）
        actions[4] = 1.0 if side_n == "buy" else 0.0

        actions[5] = float(u)

        actions[6] = _pips_to_slot(sub_limit_pips)  if sub_limit_pips  is not None else 0.0
        actions[7] = _pips_to_slot(stop_order_pips) if stop_order_pips is not None else 0.0
        actions[8] = _pips_to_slot(trail_pips)      if trail_pips      is not None else 0.0

        payload = bytes(encode_vec_f64(actions))
        raw = await self._rpc.send_run_and_wait(FN.STEP_MAKE_TICKET, payload, timeout=timeout)
        out = decode_vec_f64(raw)

        # reward5state9 => 5+9 = 14
        if out.ndim != 1 or out.size != 14:
            raise RuntimeError(f"place_ticket: invalid return shape {out.shape}, expected (14,)")

        return out





# =========================
# Auto-refresh wrapper
# =========================

@runtime_checkable
class _HasStatics(Protocol):
    statics: Statics


# ...（FN, Statics, EngineAPI は今のままでOK）...

class BoundEngine:
    def __init__(
        self,
        base: EngineAPI,
        state,
        *,
        refresh_after_reads: bool = True,
        gate_policy: str = "eager",
    ) -> None:
        self._base = base
        self._state = state
        self._gate_policy = gate_policy if gate_policy in ("eager", "step_end") else "eager"
        # lazyモードでは中間読み出し時の再取得は行わない
        self._refresh_after_reads = bool(refresh_after_reads and self._gate_policy == "eager")
    
    @staticmethod
    def _check_terminal(state, events: np.ndarray) -> None:
        # events の最後の行の benefit(col=1) を見る
        if events.size == 0:
            return
        if events.ndim != 2 or events.shape[1] != 5:
            # close_step / place_ticket などの非イベント系レスポンスは無視
            return
        last = events[-1]
        if not (last[0] == 1 and last[2] == 1 and last[3] == 1 and last[4] == 1):
            return
        code = int(last[1])
        if code in (REWARD_GAME_BREAK, REWARD_GAME_END):
            state.done = True
            state.done_code = code

    async def _refresh_only(self, timeout: float = 10.0) -> Statics:
        s = await self._base.get_statics(timeout=timeout)
        self._state.statics = s
        return s

    async def refresh(self, timeout: float = 10.0) -> Statics:
        return await self._refresh_only(timeout=timeout)

    async def affect(self, timeout: float = 10.0) -> np.ndarray:
        """
        affect 実行前後で token→ticket 変換失敗を検出してログ出力する
        """
        # ===== affect =====
        events = await self._base.affect(timeout=timeout)
        self._state.affect_events = events
        self._check_terminal(self._state, events)

        return events

    async def _gate_now(self, timeout: float = 10.0) -> Statics:
        events = await self.affect(timeout=timeout)
        self._state.affect_events = events
        self._check_terminal(self._state, events)
        return await self._refresh_only(timeout=timeout)

    async def _gate(self, timeout: float = 10.0) -> Statics:
        """
        どの操作/参照の前にも呼ぶ「整合ゲート」。
        gate_policy:
          - eager     : 毎回 gate を通す
          - step_end  : 1ステップ中はキャッシュを返し、必要なら初回だけ同期
        """
        if self._gate_policy == "step_end":
            if self._state.statics is None:
                return await self._gate_now(timeout=timeout)
            return self._state.statics
        return await self._gate_now(timeout=timeout)

    async def get_statics(self, timeout: float = 10.0) -> Statics:
        # gate_policy に従って整合化
        return await self._gate(timeout=timeout)

    async def get_ticket_list(self, timeout: float = 10.0) -> np.ndarray:
        # ★ チケット取得の前にも整合化（必要なら）
        if self._gate_policy == "eager":
            await self._gate_now(timeout=timeout)
        tickets = await self._base.get_ticket_list(timeout=timeout)
        if self._refresh_after_reads:
            await self.refresh(timeout=timeout)
        return tickets

    async def step_next(self, timeout: float = 10.0) -> None:
        # stepを進める前に整合化しても良いが、通常は step_next 後にgateをかける方が自然
        if self._gate_policy == "step_end" and hasattr(self._base, "step_next_affect_statics"):
            events, statics = await self._base.step_next_affect_statics(timeout=timeout)
            self._state.affect_events = events
            self._check_terminal(self._state, events)
            self._state.statics = statics
            return None

        await self._base.step_next(timeout=timeout)
        # step_end モードでもステップ終了時は1回だけ同期
        await self._gate_now(timeout=timeout)
        return None

    async def init_ohlc5(self, ohlc5: np.ndarray, timeout: float = 10.0) -> None:
        await self._base.init_ohlc5(ohlc5, timeout=timeout)
        await self._gate_now(timeout=timeout)
        return None
    
    async def game_end(self, timeout: float = 10.0) -> np.ndarray:
        events = await self._base.game_end(timeout=timeout)
        self._state.affect_events = events
        self._check_terminal(self._state, events)  # ← END=1 を確実に拾う
        await self._refresh_only(timeout=timeout)
        return events
    
    async def close_step(
            self,
            flags,
            actions,
            ratios,
            *,
            timeout: float = 10.0,
        ) -> np.ndarray:
            """
            close_step を実行して、内部 state を更新する。
            flags/actions/ratios は配列（複数チケットの一括決済）を想定。
            """

            # 1) WASM 実行（実体は EngineAPI）
            events = await self._base.close_step(
                flags=flags,
                actions=actions,
                ratios=ratios,
                timeout=timeout,
            )

            # 2) state に反映（既存の affect と同じ扱い）
            #   events: shape (N,5)
            self._state.affect_events = events

            # 3) 終端判定（破産 / 強制終了など）
            self._check_terminal(self._state, events)

            # 4) 次ステップ同期（WS/clock ゲート）
            if self._gate_policy == "eager":
                await self._gate_now(timeout=timeout)

            return events
        
    async def place_token(
        self,
        *,
        side: str,
        order: str,
        price: float,
        units: int,
        sub_limit_pips: float | None = None,
        stop_order_pips: float | None = None,
        trail_pips: float | None = None,
        time_limits: float | None = None,
        timeout: float = 10.0,
    ) -> np.ndarray:
        out = await self._base.place_token(
            side=side,
            order=order,
            price=price,
            units=units,
            sub_limit_pips=sub_limit_pips,
            stop_order_pips=stop_order_pips,
            trail_pips=trail_pips,
            time_limits=time_limits,
            timeout=timeout,
        )

        # 必要なら「直近イベント」として保存（ログ/可視化用）
        self._state.affect_events = out.reshape(1, -1)

        # place_token 自体は終端を作らない想定だが、一応既存の流儀に合わせるなら呼んでOK
        self._check_terminal(self._state, self._state.affect_events)
        if self._gate_policy == "eager":
            await self._gate_now(timeout=timeout)
        return out
    
    
    async def place_ticket(
        self,
        *,
        side: str,
        units: int,
        sub_limit_pips: float | None = None,
        stop_order_pips: float | None = None,
        trail_pips: float | None = None,
        timeout: float = 10.0,
    ) -> np.ndarray:
        """
        即時ticket作成 + state同期（gate） + 失敗検出ログ。
        終端判定はしない（affectでやる）。
        """

        out = await self._base.place_ticket(
            side=side,
            units=units,
            sub_limit_pips=sub_limit_pips,
            stop_order_pips=stop_order_pips,
            trail_pips=trail_pips,
            timeout=timeout,
        )

        # 直近イベントとして残す（必要なら）
        # out: shape (14,)
        try:
            self._state.last_ticket_event = out
        except Exception:
            pass

        # 成功/失敗判定（C++成功時は out[4] == -1）
        ok = (out.ndim == 1 and out.size == 14 and float(out[4]) == -1.0)

        if ok:
            flag = int(out[0])
            ticket_format = int(out[3])
            logger.info(
                "[place_ticket] created ticket flag=%d side=%s format=%d units=%s",
                flag, side, ticket_format, units
            )
        else:
            # 失敗時は out[0..4] が同一の failure code で埋まる想定
            code = float(out[0]) if (out.ndim == 1 and out.size >= 5) else None
            logger.warning(
                "[place_ticket] NOT created | side=%s units=%s "
                "sub_limit_pips=%s stop_order_pips=%s trail_pips=%s raw0_4=%s",
                side, units, sub_limit_pips, stop_order_pips, trail_pips,
                out[:5].tolist() if (out.ndim == 1 and out.size >= 5) else str(out),
            )

        # ★ ここが重要：ticket作成で資産/証拠金/virtual_assets が変わるなら同期が必要
        if self._gate_policy == "eager":
            await self._gate_now(timeout=timeout)

        return out
