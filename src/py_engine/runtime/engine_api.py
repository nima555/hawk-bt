from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import logging

logger = logging.getLogger(__name__)

REWARD_GAME_BREAK = -1
REWARD_GAME_END = 1
ACTION_REDUCE = 2


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


class BoundEngine:
    def __init__(
        self,
        base,
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
        return await self._gate(timeout=timeout)

    async def get_ticket_list(self, timeout: float = 10.0) -> np.ndarray:
        if self._gate_policy == "eager":
            await self._gate_now(timeout=timeout)
        tickets = await self._base.get_ticket_list(timeout=timeout)
        if self._refresh_after_reads:
            await self.refresh(timeout=timeout)
        return tickets

    async def step_next(self, timeout: float = 10.0) -> None:
        if self._gate_policy == "step_end" and hasattr(self._base, "step_next_affect_statics"):
            events, statics = await self._base.step_next_affect_statics(timeout=timeout)
            self._state.affect_events = events
            self._check_terminal(self._state, events)
            self._state.statics = statics
            return None

        await self._base.step_next(timeout=timeout)
        await self._gate_now(timeout=timeout)
        return None

    async def init_ohlc5(self, ohlc5: np.ndarray, timeout: float = 10.0) -> None:
        await self._base.init_ohlc5(ohlc5, timeout=timeout)
        await self._gate_now(timeout=timeout)
        return None

    async def game_end(self, timeout: float = 10.0) -> np.ndarray:
        events = await self._base.game_end(timeout=timeout)
        self._state.affect_events = events
        self._check_terminal(self._state, events)
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
            events = await self._base.close_step(
                flags=flags,
                actions=actions,
                ratios=ratios,
                timeout=timeout,
            )
            self._state.affect_events = events
            self._check_terminal(self._state, events)
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
        self._state.affect_events = out.reshape(1, -1)
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
        out = await self._base.place_ticket(
            side=side,
            units=units,
            sub_limit_pips=sub_limit_pips,
            stop_order_pips=stop_order_pips,
            trail_pips=trail_pips,
            timeout=timeout,
        )
        try:
            self._state.last_ticket_event = out
        except Exception:
            pass

        ok = (out.ndim == 1 and out.size == 14 and float(out[4]) == -1.0)

        if ok:
            flag = int(out[0])
            ticket_format = int(out[3])
            logger.info(
                "[place_ticket] created ticket flag=%d side=%s format=%d units=%s",
                flag, side, ticket_format, units
            )
        else:
            logger.warning(
                "[place_ticket] NOT created | side=%s units=%s "
                "sub_limit_pips=%s stop_order_pips=%s trail_pips=%s raw0_4=%s",
                side, units, sub_limit_pips, stop_order_pips, trail_pips,
                out[:5].tolist() if (out.ndim == 1 and out.size >= 5) else str(out),
            )

        if self._gate_policy == "eager":
            await self._gate_now(timeout=timeout)

        return out
