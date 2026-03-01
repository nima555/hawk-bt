from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class RustEngineAsyncAdapter:
    """Thin async wrapper around the Rust-backed RustEngineAsync PyO3 class."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8787, *, start_seq: int = 1):
        try:
            from py_engine_rust import RustEngineAsync as _RustEngineAsync  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"py_engine_rust is not available: {e}") from e
        self._eng = _RustEngineAsync(host, port, start_seq)

    async def start(self) -> None:
        await self._eng.start()

    async def wait_connected(self, timeout: Optional[float] = None) -> None:
        await self._eng.wait_connected(timeout)

    async def init_candles(self, ohlc5: np.ndarray, timeout: float = 10.0) -> None:
        await self._eng.init_candles(ohlc5, timeout)

    async def step_next(self, timeout: float = 10.0) -> None:
        await self._eng.step_next(timeout)

    async def step_and_sync(self, timeout: float = 10.0):
        """Step forward and return (events, Snapshot) in one RPC call."""
        from hawk_bt.runtime.engine_api import Snapshot
        events, vec = await self._eng.step_and_sync(timeout)
        events_arr = np.asarray(events)
        vec_arr = np.asarray(vec)
        return events_arr, Snapshot.from_raw_vector(vec_arr)

    async def get_snapshot_raw(self, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.get_snapshot(timeout)
        return np.asarray(out)

    async def get_snapshot(self, timeout: float = 10.0):
        """Get current engine state as a Snapshot dataclass."""
        from hawk_bt.runtime.engine_api import Snapshot
        vec = await self.get_snapshot_raw(timeout=timeout)
        return Snapshot.from_raw_vector(vec)

    async def get_ticket_list(self, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.get_ticket_list(timeout)
        return np.asarray(out)

    async def get_ohlc(self, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.get_ohlc(timeout)
        return np.asarray(out)

    async def fetch_events(self, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.fetch_events(timeout)
        return np.asarray(out)

    async def end_session(self, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.end_session(timeout)
        return np.asarray(out)

    async def close_positions(self, position_ids, actions, ratios, *, timeout: float = 10.0) -> np.ndarray:
        out = await self._eng.close_positions(position_ids, actions, ratios, timeout)
        return np.asarray(out)

    async def get_sync_policy(self, timeout: float = 5.0) -> Optional[str]:
        return await self._eng.get_sync_policy(timeout)

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
        out = await self._eng.place_order(
            side,
            order_type,
            float(price),
            int(units),
            take_profit,
            stop_loss,
            trailing_stop,
            time_limit,
            timeout,
        )
        return np.asarray(out)

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
        out = await self._eng.place_ticket(
            side,
            int(units),
            take_profit,
            stop_loss,
            trailing_stop,
            timeout,
        )
        return np.asarray(out)

    async def wait_ready(
        self,
        timeout: float = 60.0,
        min_snapshot_len: int = 14,
        poll_interval: float = 0.5,
        verbose: bool = True,
    ) -> bool:
        """Wait for the WASM engine to finish initialization.

        Args:
            timeout: Maximum wait time in seconds.
            min_snapshot_len: Minimum snapshot vector length to consider ready.
            poll_interval: Polling interval in seconds.
            verbose: Whether to log progress.

        Returns:
            True if ready, False if timed out.
        """
        if verbose:
            logger.info("Waiting for WASM engine to initialize...")

        start = time.time()
        attempt = 0
        while time.time() - start < timeout:
            attempt += 1
            try:
                snapshot = await self.get_snapshot_raw(timeout=2.0)
                if len(snapshot) >= min_snapshot_len:
                    if verbose:
                        logger.info("WASM engine initialized (%.1fs)", time.time() - start)
                    return True
            except Exception as e:
                if verbose and attempt <= 3:
                    logger.debug("Waiting for WASM... (attempt %d, %s)", attempt, e)
            await asyncio.sleep(poll_interval)

        if verbose:
            logger.warning("WASM engine initialization timed out after %.0fs", timeout)
        return False

    async def wait_for_disconnect(
        self,
        poll_interval: float = 0.5,
        verbose: bool = True,
    ) -> None:
        """Wait for the browser to disconnect.

        Args:
            poll_interval: Polling interval in seconds.
            verbose: Whether to log the event.
        """
        if verbose:
            logger.info("Waiting for browser disconnect...")

        while True:
            try:
                await self.get_snapshot_raw(timeout=1.0)
            except Exception:
                break
            await asyncio.sleep(poll_interval)

        if verbose:
            logger.info("Browser disconnected.")


__all__ = ["RustEngineAsyncAdapter"]
