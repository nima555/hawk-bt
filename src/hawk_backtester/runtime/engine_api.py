from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import logging

logger = logging.getLogger(__name__)

EXIT_MARGIN_CALL = -1
EXIT_COMPLETE = 1
ACTION_REDUCE = 2


@dataclass
class Snapshot:
    """Current engine state snapshot.

    Parsed from a raw float64 vector returned by the engine (fixed layout).
    """
    balance: float
    equity: float
    used_margin: float
    margin_level: float
    price: float
    timestamp_ms: float
    step: int
    pending_orders: float
    tickets_num: float
    ticket_all_num: float
    bar_count: int
    ticket_stat_0: float
    ticket_stat_1: float
    ticket_stat_2: float
    ticket_stat_3: float
    ticket_long_count: float
    ticket_short_count: float
    pending_long_count: float
    pending_short_count: float
    total_steps: int

    # Backward-compatible aliases (deprecated)
    @property
    def ticket_buy_count(self) -> float:
        return self.ticket_long_count

    @property
    def ticket_sell_count(self) -> float:
        return self.ticket_short_count

    @staticmethod
    def from_raw_vector(v: np.ndarray) -> "Snapshot":
        """Parse a raw float64 vector (>= 14 elements) into a Snapshot."""
        if not isinstance(v, np.ndarray):
            raise TypeError("Snapshot.from_raw_vector expects numpy.ndarray")
        v = np.asarray(v, dtype=np.float64)
        if v.shape[0] < 14:
            raise ValueError(f"snapshot vector must have >= 14 elements, got {v.shape}")

        # Expect 20 elements; pad with zeros for backward compatibility
        target_size = 20
        if v.size < target_size:
            padded = np.zeros(target_size, dtype=np.float64)
            padded[: v.size] = v
            v = padded

        return Snapshot(
            balance=float(v[0]),
            equity=float(v[1]),
            used_margin=float(v[2]),
            margin_level=float(v[3]),
            price=float(v[4]),
            timestamp_ms=float(v[5]),
            step=int(v[6]),
            pending_orders=float(v[7]),
            tickets_num=float(v[8]),
            ticket_all_num=float(v[9]),
            bar_count=int(v[10]),
            ticket_stat_0=float(v[11]),
            ticket_stat_1=float(v[12]),
            ticket_stat_2=float(v[13]),
            ticket_stat_3=float(v[14]),
            ticket_long_count=float(v[15]),
            ticket_short_count=float(v[16]),
            pending_long_count=float(v[17]),
            pending_short_count=float(v[18]),
            total_steps=int(v[19]),
        )


class Engine:
    """Wraps a base engine adapter with consistency guarantees.

    Every read/write goes through a synchronization gate that keeps
    ``state.snapshot`` always up-to-date.  Two sync modes are supported:

    - ``"eager"``    : sync after every operation (safest, default).
    - ``"deferred"`` : sync only at step boundaries (faster for batched ops).
    """

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
        # Normalize legacy value
        if gate_policy == "step_end":
            gate_policy = "deferred"
        self._gate_policy = gate_policy if gate_policy in ("eager", "deferred") else "eager"
        self._refresh_after_reads = bool(refresh_after_reads and self._gate_policy == "eager")

    @staticmethod
    def _check_terminal(state, events: np.ndarray) -> None:
        """Check if the last event signals a terminal state (margin call / session end)."""
        if events.size == 0:
            return
        if events.ndim != 2 or events.shape[1] != 5:
            return
        last = events[-1]
        if not (last[0] == 1 and last[2] == 1 and last[3] == 1 and last[4] == 1):
            return
        code = int(last[1])
        if code in (EXIT_MARGIN_CALL, EXIT_COMPLETE):
            state.done = True
            state.exit_code = code

    async def _refresh_only(self, timeout: float = 10.0) -> Snapshot:
        s = await self._base.get_snapshot(timeout=timeout)
        self._state.snapshot = s
        return s

    async def refresh(self, timeout: float = 10.0) -> Snapshot:
        return await self._refresh_only(timeout=timeout)

    async def fetch_events(self, timeout: float = 10.0) -> np.ndarray:
        events = await self._base.fetch_events(timeout=timeout)
        self._state.events = events
        self._check_terminal(self._state, events)
        return events

    async def _sync(self, timeout: float = 10.0) -> Snapshot:
        """Fetch events and refresh snapshot (full synchronization)."""
        events = await self.fetch_events(timeout=timeout)
        self._state.events = events
        self._check_terminal(self._state, events)
        return await self._refresh_only(timeout=timeout)

    async def _ensure_synced(self, timeout: float = 10.0) -> Snapshot:
        """Consistency gate called before any read/write.

        In eager mode, always syncs.  In deferred mode, syncs only once
        per step (returns cached snapshot otherwise).
        """
        if self._gate_policy == "deferred":
            if self._state.snapshot is None:
                return await self._sync(timeout=timeout)
            return self._state.snapshot
        return await self._sync(timeout=timeout)

    async def get_snapshot(self, timeout: float = 10.0) -> Snapshot:
        return await self._ensure_synced(timeout=timeout)

    async def get_ticket_list(self, timeout: float = 10.0) -> np.ndarray:
        if self._gate_policy == "eager":
            await self._sync(timeout=timeout)
        tickets = await self._base.get_ticket_list(timeout=timeout)
        if self._refresh_after_reads:
            await self.refresh(timeout=timeout)
        return tickets

    async def step_next(self, timeout: float = 10.0) -> None:
        if self._gate_policy == "deferred" and hasattr(self._base, "step_and_sync"):
            events, snapshot = await self._base.step_and_sync(timeout=timeout)
            self._state.events = events
            self._check_terminal(self._state, events)
            self._state.snapshot = snapshot
            return None

        await self._base.step_next(timeout=timeout)
        await self._sync(timeout=timeout)
        return None

    async def init_candles(self, ohlc5: np.ndarray, timeout: float = 10.0) -> None:
        await self._base.init_candles(ohlc5, timeout=timeout)
        await self._sync(timeout=timeout)
        return None

    async def end_session(self, timeout: float = 10.0) -> np.ndarray:
        events = await self._base.end_session(timeout=timeout)
        self._state.events = events
        self._check_terminal(self._state, events)
        await self._refresh_only(timeout=timeout)
        return events

    async def close_positions(
            self,
            position_ids,
            actions,
            ratios,
            *,
            timeout: float = 10.0,
        ) -> np.ndarray:
            events = await self._base.close_positions(
                position_ids=position_ids,
                actions=actions,
                ratios=ratios,
                timeout=timeout,
            )
            self._state.events = events
            self._check_terminal(self._state, events)
            if self._gate_policy == "eager":
                await self._sync(timeout=timeout)
            return events

    async def place_order(
        self,
        *,
        side: str,
        order_type: str,
        price: float,
        units: int,
        take_profit: float | None = None,
        stop_loss: float | None = None,
        trailing_stop: float | None = None,
        time_limit: float | None = None,
        timeout: float = 10.0,
    ) -> np.ndarray:
        out = await self._base.place_order(
            side=side,
            order_type=order_type,
            price=price,
            units=units,
            take_profit=take_profit,
            stop_loss=stop_loss,
            trailing_stop=trailing_stop,
            time_limit=time_limit,
            timeout=timeout,
        )
        self._state.events = out.reshape(1, -1)
        self._check_terminal(self._state, self._state.events)
        if self._gate_policy == "eager":
            await self._sync(timeout=timeout)
        return out

    async def place_ticket(
        self,
        *,
        side: str,
        units: int,
        take_profit: float | None = None,
        stop_loss: float | None = None,
        trailing_stop: float | None = None,
        timeout: float = 10.0,
    ) -> np.ndarray:
        out = await self._base.place_ticket(
            side=side,
            units=units,
            take_profit=take_profit,
            stop_loss=stop_loss,
            trailing_stop=trailing_stop,
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
            logger.debug(
                "Ticket created: flag=%d side=%s format=%d units=%s",
                flag, side, ticket_format, units,
            )
        else:
            logger.warning(
                "Ticket NOT created | side=%s units=%s "
                "take_profit=%s stop_loss=%s trailing_stop=%s raw[0:5]=%s",
                side, units, take_profit, stop_loss, trailing_stop,
                out[:5].tolist() if (out.ndim == 1 and out.size >= 5) else str(out),
            )

        if self._gate_policy == "eager":
            await self._sync(timeout=timeout)

        return out
